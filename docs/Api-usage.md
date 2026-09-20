# FastApi Api Scaffold
A minimal FastAPI scaffold showcasing bearer-token authentication, standard request/response handling, and streaming responses via Server‑Sent Events (SSE).    
    
Intended as a foundation for API development and refactoring.  

## Installation
### Set using of Bearer token in .env
```
API_KEY=Anything you like, i.e. sk-1234
USE_API_KEY=false | true (value is case-insensitive)
```
       
On request, use in Authorization header like so:
```
Authorization: Bearer sk-1234
```
    
### Build Docker image and start container
```
docker-compose build
docker-compose up
```

## Quicktest
### Using the VSC Extension [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client) by Huachao Mao
This Extension is quite convenient for quick tests *within* VSC.   
In VSC: open the file `test_request.http` and uncomment the respective request you like to test. A small clickable "send request" text appears above the url request.    
The response is then opened in a new tab in the VSC editor.

### Curl
- Simple GET request
```
curl -H "Authorization: Bearer sk-1234" "http://localhost:10100/simple/get-request?number=2&text=Some%20random%20text&boolean=true"
```
- Simple POST request
```
curl -H "Content-Type: application/json" -H "Authorization: Bearer sk-1234" -d '{"number": 2, "text": "Some random text", "boolean": true}' http://localhost:10100/simple/post-request
```
- Stream Request (GET)
```
curl -N -H "Accept: text/event-stream" -H "Authorization: Bearer sk-1234" http://localhost:10100/stream/get-request
```

### Test Streaming via Script
Attach a new container shell to the terminal and call `stream_request_test.py` and call the script
```
python -m stream_request_test
```
    
This is just an example for programatically using the stream.    

## Description
Written by GPT 5.2    

### Overview

This project is a lightweight FastAPI-based API scaffold that demonstrates common backend patterns such as authenticated REST endpoints, structured request/response handling with Pydantic models, and server-sent events (SSE) for streaming responses. It is intended as a starting point or reference for building and refactoring FastAPI services, with a clear separation between routing, business logic, data models, and configuration.

### Architecture and Component Interaction

The application is initialized in `src/app.py`, where the FastAPI instance is created, global authentication is applied, routers are registered, and shared exception handling is defined. Incoming requests first pass through an optional bearer-token authentication dependency before being dispatched to the appropriate router. Each router validates input and delegates processing to a dedicated class, while Pydantic models define the API contract for inputs, outputs, and streamed events.

Routing logic lives under `src/routes`, domain logic under `src/classes`, and data schemas under `src/models`. Configuration and authentication are handled centrally, ensuring consistent behavior across all endpoints.

### Routes

#### Request Flow

For non-streaming endpoints, an incoming HTTP request first passes through the optional bearer-token authentication dependency. After successful authentication, FastAPI validates query parameters or request bodies, depending on the endpoint. The request is then routed to the corresponding handler, which delegates processing to a domain class (such as `SimpleRequest`). The result is returned as a structured JSON response, optionally validated and serialized using Pydantic response models.

The root routes (`/`) defined in `root_route.py` provide simple GET and POST endpoints mainly for health checks and basic connectivity testing. These endpoints are intentionally left unauthenticated.

The simple request routes in `simple_request_route.py` expose both a GET and a POST endpoint. The GET endpoint accepts query parameters and relies on FastAPI’s built-in validation, while the POST endpoint uses a Pydantic model to validate the request body. Both routes instantiate the `SimpleRequest` class to process the input and return a normalized JSON response.

#### Streaming

The streaming route in `stream_request_route.py` exposes a GET endpoint that returns a server-sent events (SSE) stream. When the endpoint is called, a `StreamingResponse` is opened immediately and events are sent incrementally to the client. The `StreamRequest` class performs asynchronous processing in the background, emitting progress updates, intermediate states, and the final merged result as individual SSE messages. This allows clients to react to long-running operations in real time instead of waiting for a single final response.

### Classes

The `SimpleRequest` class encapsulates the business logic for non-streaming requests. It stores validated input values and exposes a method that returns a cleaned and normalized data structure. This keeps processing logic separate from HTTP concerns and makes the code easier to extend or test.

The `StreamRequest` class implements an asynchronous processing pipeline that simulates calling multiple external services in parallel. It emits structured SSE events that describe each stage of processing, including data collection, merging, and final results. This class demonstrates how to combine `asyncio`, background processing, and streaming responses in FastAPI.

### Models

Pydantic models in `simple_request_models.py` define the schema for simple request inputs and responses, ensuring consistent validation and serialization. Response models explicitly describe the structure returned to the client, including status and payload.

The models in `stream_request_models.py` define the structure of streamed events and domain objects used during streaming. The flexible `StreamEvent` model allows different event types to include different payloads while maintaining a consistent event envelope.

### Authentication and Configuration

Authentication is implemented as a FastAPI dependency in `auth.py` and applied globally. It validates bearer tokens against values loaded from environment variables. Configuration is managed via `settings.py` using `pydantic-settings`, allowing environment-based configuration without hardcoding secrets or flags.

---

## Sequence Diagram

```
Client
  |
  |  HTTP Request (GET / POST)
  v
FastAPI App (app.py)
  |
  |--[Auth Dependency]
  |        |
  |        |-- validate Bearer token
  |        v
  |--[Router]
  |        |
  |        |-- validate input (query / body)
  |        |-- call domain class
  |        v
  |--[Classes]
  |        |
  |        |-- SimpleRequest.get_processed_data()
  |        |-- StreamRequest.process_sse()
  |        v
  |--[Models]
  |        |
  |        |-- serialize JSON / SSE events
  |        v
Client  <---- JSON response / SSE stream
```
