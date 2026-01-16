import json
from copy import deepcopy
from typing import Any

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Role, Choice, Request, Message, Stage
from pydantic import StrictStr

from task.coordination.gpa import GPAGateway
from task.coordination.ums_agent import UMSAgentGateway
from task.logging_config import get_logger
from task.models import CoordinationRequest, AgentName
from task.prompts import COORDINATION_REQUEST_SYSTEM_PROMPT, FINAL_RESPONSE_SYSTEM_PROMPT
from task.stage_util import StageProcessor

logger = get_logger(__name__)


class MASCoordinator:

    def __init__(self, endpoint: str, deployment_name: str, ums_agent_endpoint: str, gpa_agent_endpoint: str):
        self.endpoint = endpoint
        self.deployment_name = deployment_name
        self.ums_agent_endpoint = ums_agent_endpoint
        self.gpa_agent_endpoint = gpa_agent_endpoint

    async def handle_request(self, choice: Choice, request: Request, api_key: str) -> Message:
        # Create AsyncDial client with API key
        logger.info(f"Creating AsyncDial client with endpoint: {self.endpoint}, api_key: {api_key[:10] if len(api_key) > 10 else api_key}")
        logger.info(f"Request has {len(request.messages)} messages")
        client = AsyncDial(base_url=self.endpoint, api_version='2025-01-01-preview', api_key=api_key)
        
        # Open stage for Coordination Request
        coordination_stage = StageProcessor.open_stage(choice, "Coordination Request")
        
        try:
            # Prepare coordination request
            coordination_request = await self.__prepare_coordination_request(client, request)
            
            # Add to the stage generated coordination request and close the stage
            # Note: Stages don't have append method, we'll just close it since the routing info
            # is already visible through the stage name and the agent response stage
            StageProcessor.close_stage_safely(coordination_stage)
            
            # Handle coordination request
            agent_stage = StageProcessor.open_stage(choice, f"{coordination_request.agent_name} Agent Response")
            try:
                agent_message = await self.__handle_coordination_request(
                    coordination_request,
                    choice,
                    agent_stage,
                    request,
                    api_key
                )
                logger.info(f"Agent message received - Content length: {len(agent_message.content) if agent_message.content else 0}")
                logger.info(f"Agent message content preview: {agent_message.content[:200] if agent_message.content else 'None'}...")
                logger.info(f"Agent message has custom_content: {agent_message.custom_content is not None}")
            finally:
                StageProcessor.close_stage_safely(agent_stage)
            
            # The agent message is already written to the agent stage and contains the complete response
            # In DIAL SDK, content written to stages during execution is what gets displayed
            # We return the message for consistency, but the actual display comes from what was written to stages
            logger.info(f"Returning agent message - Role: {agent_message.role}, Content length: {len(agent_message.content) if agent_message.content else 0}")
            return agent_message
        except Exception as e:
            StageProcessor.close_stage_safely(coordination_stage)
            raise

    async def __prepare_coordination_request(self, client: AsyncDial, request: Request) -> CoordinationRequest:
        messages = self.__prepare_messages(request, COORDINATION_REQUEST_SYSTEM_PROMPT)
        
        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": CoordinationRequest.model_json_schema()
                }
            }
        }
        
        try:
            response = await client.chat.completions.create(
                deployment_name=self.deployment_name,
                messages=messages,
                extra_body=extra_body
            )
        except Exception as e:
            logger.error(f"Error calling DIAL endpoint: {e}")
            logger.error(f"Endpoint: {self.endpoint}, Deployment: {self.deployment_name}")
            raise
        
        content = response.choices[0].message.content
        result_dict = json.loads(content)
        coordination_request = CoordinationRequest.model_validate(result_dict)
        
        return coordination_request

    def __prepare_messages(self, request: Request, system_prompt: str) -> list[dict[str, Any]]:
        messages = [{"role": "system", "content": system_prompt}]
        
        for message in request.messages:
            if message.role == Role.USER and message.custom_content:
                # User message with custom content - add message with content, skip custom_content
                messages.append({
                    "role": "user",
                    "content": message.content
                })
            else:
                # Regular message - append as dict with excluded none fields
                msg_dict = message.dict(exclude_none=True)
                messages.append(msg_dict)
        
        return messages

    async def __handle_coordination_request(
            self,
            coordination_request: CoordinationRequest,
            choice: Choice,
            stage: Stage,
            request: Request,
            api_key: str
    ) -> Message:
        if coordination_request.agent_name == AgentName.UMS:
            ums_gateway = UMSAgentGateway(self.ums_agent_endpoint)
            return await ums_gateway.response(
                choice=choice,
                stage=stage,
                request=request,
                additional_instructions=coordination_request.additional_instructions
            )
        elif coordination_request.agent_name == AgentName.GPA:
            gpa_gateway = GPAGateway(self.gpa_agent_endpoint)
            # Get API key from request headers for GPA service (GPA service uses the same API key as the user provides)
            gpa_api_key = request.headers.get('Api-Key') or request.headers.get('api-key') if request.headers else None
            if not gpa_api_key:
                # Fallback to the api_key parameter if headers don't have it
                gpa_api_key = api_key
            return await gpa_gateway.response(
                choice=choice,
                stage=stage,
                request=request,
                additional_instructions=coordination_request.additional_instructions,
                api_key=gpa_api_key
            )
        else:
            raise ValueError(f"Unknown agent name: {coordination_request.agent_name}")

    async def __final_response(
            self, client: AsyncDial,
            choice: Choice,
            request: Request,
            agent_message: Message
    ) -> Message:
        messages = self.__prepare_messages(request, FINAL_RESPONSE_SYSTEM_PROMPT)
        
        # Augment with agent response as context and user request
        last_user_message = request.messages[-1].content
        augmented_content = f"Context from agent:\n{agent_message.content}\n\nUser request: {last_user_message}"

        # Update last message content with augmented prompt
        messages[-1]["content"] = augmented_content

        # Call LLM with streaming
        stream = await client.chat.completions.create(
            deployment_name=self.deployment_name,
            messages=messages,
            stream=True
        )

        # Stream final response content directly to the choice
        # In DIAL SDK, we need to write to the choice's message during execution
        # Try using choice.append() if available, otherwise collect and return
        content = ""
        try:
            # Try to write directly to choice if it supports append
            if hasattr(choice, 'append'):
                async for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            content += delta.content
                            choice.append(delta.content)
            else:
                # Fallback: collect content and return it
                async for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            content += delta.content
        except Exception as e:
            logger.warning(f"Could not write to choice directly: {e}, collecting content instead")
            # Fallback: collect all content
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        content += delta.content
        
        # Return Message with content
        # Include custom_content from agent_message if present
        return Message(
            role=Role.ASSISTANT, 
            content=content, 
            custom_content=agent_message.custom_content if agent_message.custom_content else None
        )
