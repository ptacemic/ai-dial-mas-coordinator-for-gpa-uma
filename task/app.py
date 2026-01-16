import os

import uvicorn
from aidial_sdk import DIALApp
from aidial_sdk.chat_completion import ChatCompletion, Request, Response

from task.agent import MASCoordinator
from task.logging_config import setup_logging, get_logger

DIAL_ENDPOINT = os.getenv('DIAL_ENDPOINT', "http://localhost:8080")
DEPLOYMENT_NAME = os.getenv('DEPLOYMENT_NAME', 'gpt-4o')
UMS_AGENT_ENDPOINT = os.getenv('UMS_AGENT_ENDPOINT', "http://localhost:8042")
GPA_AGENT_ENDPOINT = os.getenv('GPA_AGENT_ENDPOINT', "http://localhost:8052")
DIAL_API_KEY = os.getenv('DIAL_API_KEY', 'dial_api_key')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

setup_logging(log_level=LOG_LEVEL)
logger = get_logger(__name__)


class MASCoordinatorApplication(ChatCompletion):

    async def chat_completion(self, request: Request, response: Response) -> None:
        # Create single choice and open it
        choice = response.create_choice()
        choice.open()
        # Get API key for core service calls
        # Note: The core service expects 'dial_api_key' as configured in core/config.json
        # We always use 'dial_api_key' for internal calls to the core service, regardless of
        # what API key the user sends in the request header
        api_key = 'dial_api_key'  # Always use dial_api_key for core service calls
        logger.info(f"Using API key: {api_key} for core service calls")
        logger.info(f"DIAL_ENDPOINT: {DIAL_ENDPOINT}, DEPLOYMENT_NAME: {DEPLOYMENT_NAME}")
        # Create MASCoordinator and handle request
        coordinator = MASCoordinator(
            endpoint=DIAL_ENDPOINT,
            deployment_name=DEPLOYMENT_NAME,
            ums_agent_endpoint=UMS_AGENT_ENDPOINT,
            gpa_agent_endpoint=GPA_AGENT_ENDPOINT
        )
        await coordinator.handle_request(choice, request, api_key)


# Create DIALApp
app = DIALApp()

# Create MASCoordinatorApplication
agent_app = MASCoordinatorApplication()

# Add to created DIALApp chat_completion with deployment_name="mas-coordinator"
app.add_chat_completion(
    deployment_name="mas-coordinator",
    impl=agent_app
)

# Run it with uvicorn
if __name__ == "__main__":
    uvicorn.run(app, port=8055, host="0.0.0.0")

