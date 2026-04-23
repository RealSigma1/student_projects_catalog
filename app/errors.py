from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_exception_handler(request, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        field = " -> ".join(str(item) for item in error.get("loc", [])[1:])
        message = error.get("msg", "Validation error")
        messages.append(f"{field}: {message}" if field else message)
    return JSONResponse(status_code=422, content={"detail": "; ".join(messages)})
