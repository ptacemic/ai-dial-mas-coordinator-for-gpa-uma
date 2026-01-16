from copy import deepcopy
from typing import Optional, Any

from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Role, Choice, Request, Message, CustomContent, Stage, Attachment
from pydantic import StrictStr

from task.stage_util import StageProcessor

_IS_GPA = "is_gpa"
_GPA_MESSAGES = "gpa_messages"


class GPAGateway:

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    async def response(
            self,
            choice: Choice,
            stage: Stage,
            request: Request,
            additional_instructions: Optional[str],
            api_key: Optional[str] = None
    ) -> Message:
        # Create AsyncDial client
        # The endpoint should be the GPA service endpoint (default: http://localhost:8052)
        # Get API key from request headers if not provided
        if not api_key:
            api_key = request.headers.get('Api-Key') or request.headers.get('api-key') if request.headers else None
        
        if not api_key:
            raise ValueError("API key is required for GPA gateway. Provide it via api_key parameter or Api-Key header.")
        
        client = AsyncDial(base_url=self.endpoint, api_version='2025-01-01-preview', api_key=api_key)
        
        # Prepare messages for GPA
        messages = self.__prepare_gpa_messages(request, additional_instructions)
        
        # Prepare extra headers
        extra_headers = {}
        if request.headers and request.headers.get('x-conversation-id'):
            extra_headers['x-conversation-id'] = request.headers.get('x-conversation-id')
        
        # Make call to general-purpose-agent
        stream = await client.chat.completions.create(
            deployment_name="general-purpose-agent",
            messages=messages,
            stream=True,
            extra_headers=extra_headers if extra_headers else None
        )
        
        # Variables for collecting response
        content = ""
        result_custom_content = CustomContent(attachments=[], state=None)
        stages_map: dict[int, Stage] = {}
        chunk_count = 0
        
        from task.logging_config import get_logger
        logger = get_logger(__name__)
        
        # Process streaming response
        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                
                # Handle content
                if delta.content:
                    content += delta.content
                    chunk_count += 1
                    # Append to choice - this is the correct way to write content in DIAL SDK
                    try:
                        choice.append_content(delta.content)
                    except Exception as e:
                        logger.warning(f"Could not append to choice: {e}")
                
                # Handle custom_content
                if delta.custom_content:
                    # Convert custom_content to dict
                    if hasattr(delta.custom_content, 'dict'):
                        custom_content_dict = delta.custom_content.dict(exclude_none=True)
                    elif hasattr(delta.custom_content, '__dict__'):
                        custom_content_dict = {k: v for k, v in delta.custom_content.__dict__.items() if v is not None}
                    else:
                        custom_content_dict = {}
                    
                    # Handle attachments
                    if 'attachments' in custom_content_dict and custom_content_dict['attachments']:
                        for attachment in custom_content_dict['attachments']:
                            if hasattr(attachment, 'dict'):
                                result_custom_content.attachments.append(
                                    Attachment(**attachment.dict(exclude_none=True))
                                )
                            else:
                                result_custom_content.attachments.append(
                                    Attachment(**attachment if isinstance(attachment, dict) else attachment.__dict__)
                                )
                    
                    # Handle state
                    if 'state' in custom_content_dict and custom_content_dict['state']:
                        if result_custom_content.state is None:
                            result_custom_content.state = {}
                        if isinstance(custom_content_dict['state'], dict):
                            result_custom_content.state.update(custom_content_dict['state'])
                    
                    # Handle stages propagation
                    if 'stages' in custom_content_dict:
                        for stg in custom_content_dict['stages']:
                            if 'index' in stg:
                                idx = stg['index']
                                if idx in stages_map:
                                    # Update existing stage
                                    existing_stage = stages_map[idx]
                                    if 'content' in stg:
                                        try:
                                            # Write content to choice, not stage
                                            choice.append_content(stg['content'])
                                        except:
                                            pass
                                    if 'attachments' in stg:
                                        for attachment in stg['attachments']:
                                            try:
                                                if hasattr(attachment, 'dict'):
                                                    existing_stage.add_attachment(
                                                        Attachment(**attachment.dict(exclude_none=True))
                                                    )
                                                else:
                                                    existing_stage.add_attachment(
                                                        Attachment(**attachment if isinstance(attachment, dict) else attachment.__dict__)
                                                    )
                                            except:
                                                pass
                                    if 'status' in stg and stg['status'] == 'completed':
                                        StageProcessor.close_stage_safely(existing_stage)
                                else:
                                    # Create new stage
                                    new_stage = StageProcessor.open_stage(choice, stg.get('name'))
                                    stages_map[idx] = new_stage
                                    if 'content' in stg:
                                        try:
                                            # Write content to choice, not stage
                                            choice.append_content(stg['content'])
                                        except:
                                            pass
                                    if 'attachments' in stg:
                                        for attachment in stg['attachments']:
                                            try:
                                                if hasattr(attachment, 'dict'):
                                                    new_stage.add_attachment(
                                                        Attachment(**attachment.dict(exclude_none=True))
                                                    )
                                                else:
                                                    new_stage.add_attachment(
                                                        Attachment(**attachment if isinstance(attachment, dict) else attachment.__dict__)
                                                    )
                                            except:
                                                pass
        
        # Save GPA conversation state to choice state
        if result_custom_content.state:
            choice.set_state({_IS_GPA: True, _GPA_MESSAGES: result_custom_content.state})
        
        logger.info(f"GPA response collected - Total chunks: {chunk_count}, Content length: {len(content)}")
        logger.info(f"GPA response content preview: {content[:200] if content else 'None'}...")
        
        # Return assistant message with content and custom_content
        # Custom content (attachments, state) should be part of the Message, not set on Choice
        if result_custom_content.attachments or result_custom_content.state:
            return Message(
                role=Role.ASSISTANT,
                content=content,
                custom_content=result_custom_content
            )
        else:
            return Message(role=Role.ASSISTANT, content=content)

    def __prepare_gpa_messages(self, request: Request, additional_instructions: Optional[str]) -> list[dict[str, Any]]:
        res_messages = []
        
        # Iterate through request messages
        for idx in range(len(request.messages)):
            message = request.messages[idx]
            
            if message.role == Role.ASSISTANT:
                # Check if it has custom content with state
                if message.custom_content and message.custom_content.state:
                    state = message.custom_content.state
                    if isinstance(state, dict) and state.get(_IS_GPA) is True:
                        # Add user message (previous message)
                        if idx > 0:
                            user_msg = request.messages[idx - 1]
                            res_messages.append(user_msg.dict(exclude_none=True))
                        
                        # Restore assistant message with state from _GPA_MESSAGES
                        assistant_msg = deepcopy(message)
                        if _GPA_MESSAGES in state:
                            # Create new message with restored state
                            msg_dict = assistant_msg.dict(exclude_none=True)
                            if 'custom_content' not in msg_dict:
                                msg_dict['custom_content'] = {}
                            if 'state' not in msg_dict.get('custom_content', {}):
                                msg_dict['custom_content']['state'] = {}
                            msg_dict['custom_content']['state'] = state[_GPA_MESSAGES]
                            res_messages.append(msg_dict)
        
        # Add last message (user message)
        if request.messages:
            last_msg = request.messages[-1]
            last_msg_dict = last_msg.dict(exclude_none=True)
            
            # Augment with additional instructions if present
            if additional_instructions:
                if 'content' in last_msg_dict:
                    last_msg_dict['content'] = f"{last_msg_dict['content']}\n\nAdditional instructions: {additional_instructions}"
                else:
                    last_msg_dict['content'] = f"Additional instructions: {additional_instructions}"
            
            res_messages.append(last_msg_dict)
        
        return res_messages
