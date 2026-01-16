import json
from typing import Optional

import httpx
from aidial_sdk.chat_completion import Role, Request, Message, Stage, Choice
from pydantic import StrictStr


_UMS_CONVERSATION_ID = "ums_conversation_id"


class UMSAgentGateway:

    def __init__(self, ums_agent_endpoint: str):
        self.ums_agent_endpoint = ums_agent_endpoint

    async def response(
            self,
            choice: Choice,
            stage: Stage,
            request: Request,
            additional_instructions: Optional[str]
    ) -> Message:
        # Get UMS conversation id
        conversation_id = self.__get_ums_conversation_id(request)
        
        # If no conversation id found, create new conversation
        if not conversation_id:
            conversation_id = await self.__create_ums_conversation()
            # Set conversation id to choice state
            choice.set_state({_UMS_CONVERSATION_ID: conversation_id})
        
        # Get last message (user message) and augment with additional instructions
        last_message = request.messages[-1]
        user_message = last_message.content
        
        if additional_instructions:
            user_message = f"{user_message}\n\nAdditional instructions: {additional_instructions}"
        
        # Call UMS Agent
        content = await self.__call_ums_agent(conversation_id, user_message, choice)
        
        # Return assistant message
        return Message(role=Role.ASSISTANT, content=content)


    def __get_ums_conversation_id(self, request: Request) -> Optional[str]:
        """Extract UMS conversation ID from previous messages if it exists"""
        for message in request.messages:
            if message.role == Role.ASSISTANT and message.custom_content:
                state = message.custom_content.state
                if state and isinstance(state, dict) and _UMS_CONVERSATION_ID in state:
                    return state[_UMS_CONVERSATION_ID]
        return None

    async def __create_ums_conversation(self) -> str:
        """Create a new conversation on UMS agent side"""
        async with httpx.AsyncClient() as client:
            try:
                # Try with empty JSON body
                response = await client.post(
                    f"{self.ums_agent_endpoint}/conversations",
                    json={},
                    headers={"Content-Type": "application/json"},
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                return result["id"]
            except httpx.HTTPStatusError as e:
                import logging
                logger = logging.getLogger(__name__)
                error_detail = ""
                try:
                    error_detail = e.response.json()
                except:
                    error_detail = e.response.text
                logger.error(f"Failed to create UMS conversation: {e.response.status_code}")
                logger.error(f"Error details: {error_detail}")
                logger.error(f"Request URL: {e.request.url}")
                # If conversation creation fails, we can still proceed without it
                # Generate a temporary conversation ID
                import uuid
                temp_id = str(uuid.uuid4())
                logger.warning(f"Using temporary conversation ID: {temp_id}")
                return temp_id

    async def __call_ums_agent(
            self,
            conversation_id: str,
            user_message: str,
            choice: Choice
    ) -> str:
        """Call UMS agent and stream the response"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.ums_agent_endpoint}/conversations/{conversation_id}/chat",
                json={
                    "message": {
                        "role": "user",
                        "content": user_message
                    },
                    "stream": True
                },
                headers={"Content-Type": "application/json"},
                timeout=300.0
            )
            response.raise_for_status()
            
            content = ""
            chunk_count = 0
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                
                # Remove "data: " prefix
                if line.startswith("data: "):
                    data_str = line[6:]
                else:
                    data_str = line
                
                # Check for [DONE]
                if data_str.strip() == "[DONE]":
                    break
                
                try:
                    data = json.loads(data_str)
                    
                    # Handle conversation_id in response
                    if "conversation_id" in data:
                        continue
                    
                    # Extract content from choices
                    if "choices" in data and len(data["choices"]) > 0:
                        delta = data["choices"][0].get("delta", {})
                        if "content" in delta:
                            chunk = delta["content"]
                            content += chunk
                            chunk_count += 1
                            # Append to choice - this is the correct way to write content in DIAL SDK
                            try:
                                choice.append_content(chunk)
                            except Exception as e:
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.warning(f"Could not append to choice: {e}")
                except json.JSONDecodeError:
                    continue
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"UMS response collected - Total chunks: {chunk_count}, Content length: {len(content)}")
            logger.info(f"UMS response content preview: {content[:200] if content else 'None'}...")
            
            return content