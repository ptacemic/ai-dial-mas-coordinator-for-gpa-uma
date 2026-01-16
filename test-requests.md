# Test Requests for Task 1

**Note**: The API key to use is `dial_api_key` (as configured in `core/config.json`). This is different from the `DIAL_API_KEY` environment variable used internally by services.

## Troubleshooting

If you get a 500 error, check the following:

1. **Set DIAL_API_KEY environment variable** (CRITICAL):
   
   The `general-purpose-agent` and `ums-agent` services need the `DIAL_API_KEY` environment variable to be set when docker-compose starts. You have two options:
   
   **Option A: Create a `.env` file** (recommended):
   ```bash
   # Copy the example file
   cp .env.example .env
   # Edit .env and add your actual API key
   nano .env  # or use your preferred editor
   ```
   
   **Option B: Export before running docker-compose**:
   ```bash
   export DIAL_API_KEY=your_actual_api_key_here
   docker-compose up -d
   ```
   
   **Option C: Pass it inline**:
   ```bash
   DIAL_API_KEY=your_actual_api_key_here docker-compose up -d
   ```
   
   After setting the environment variable, restart the services:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

2. **Verify the API key is set in the container**:
   ```bash
   docker-compose exec general-purpose-agent env | grep DIAL_API_KEY
   # Should show your API key, not be empty
   ```

3. **Check service logs** for authentication errors:
   ```bash
   docker-compose logs general-purpose-agent --tail=50
   # Look for "Unknown api key" or "DIAL_API_KEY variable is not set"
   ```

4. **Verify you're using the actual API key in requests** (not the literal string "YOUR_API_KEY"):
   ```bash
   echo $DIAL_API_KEY  # Should show your actual API key
   ```

5. **Verify all services are running**:
   ```bash
   docker-compose ps
   ```

6. **Check if core service is accessible** (general-purpose-agent connects to `http://core:8080`):
   ```bash
   curl http://localhost:8080/health  # or check core logs
   ```

7. **CRITICAL: Complete Task 2 first**: 
   
   The general-purpose-agent **requires Task 2 to be completed** before it will work. The core service must be configured with:
   - GPT and DALL-E models
   - The general-purpose-agent application registration
   
   Even if the API key is correct, you'll get "Unknown api key" errors if Task 2 isn't done, because the core service needs to be properly configured.
   
   **To fix the current error:**
   1. Complete Task 2 from the README (configure core/config.json with models and applications)
   2. Restart the core service: `docker-compose restart core`
   3. Wait a few seconds for the core service to reload its configuration
   4. Try your request again

8. **Verify API key matches core configuration**:
   

## POST Request to General Purpose Agent

### Using curl:
```bash
curl -X POST http://localhost:8052/openai/deployments/general-purpose-agent/chat/completions \
  -H "Content-Type: application/json" \
  -H "Api-Key: dial_api_key" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "hi?"
      }
    ]
  }'
```

### Using curl (the API key is `dial_api_key`):
```bash
curl -X POST http://localhost:8052/openai/deployments/general-purpose-agent/chat/completions \
  -H "Content-Type: application/json" \
  -H "Api-Key: dial_api_key" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "hi?"
      }
    ]
  }'
```

### Using curl with pretty JSON output:
```bash
curl -X POST http://localhost:8052/openai/deployments/general-purpose-agent/chat/completions \
  -H "Content-Type: application/json" \
  -H "Api-Key: dial_api_key" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "hi?"
      }
    ]
  }' | jq .
```

### Using httpie:
```bash
http POST http://localhost:8052/openai/deployments/general-purpose-agent/chat/completions \
  Api-Key:dial_api_key \
  messages:='[{"role": "user", "content": "hi?"}]'
```

### Request Details:
- **URL**: `http://localhost:8052/openai/deployments/general-purpose-agent/chat/completions`
- **Method**: `POST`
- **Headers**: 
  - `Content-Type: application/json`
  - `Api-Key: dial_api_key` (required - matches the key configured in `core/config.json`)
- **Body**:
```json
{
  "messages": [
    {
      "role": "user",
      "content": "hi?"
    }
  ]
}
```

## Additional Test Requests

### Test with a more complex query:
```bash
curl -X POST http://localhost:8052/openai/deployments/general-purpose-agent/chat/completions \
  -H "Content-Type: application/json" \
  -H "Api-Key: dial_api_key" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "What is the weather in Kyiv?"
      }
    ]
  }'
```

### Test UMS Agent (for creating new conversation):
```bash
curl -X POST http://localhost:8042/openai/deployments/ums-agent/chat/completions \
  -H "Content-Type: application/json" \
  -H "Api-Key: dial_api_key" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "Do we have Andrej Karpathy as a user?"
      }
    ]
  }'
```
