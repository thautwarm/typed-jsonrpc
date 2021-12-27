import typing

Json = list["Json"] | dict[str, "Json"] | int | float | str | None

CANCEL_METHOD = "$/cancelRequest"
JSONRPC_VERSION = "2.0"

class  ResponseError(typing.TypedDict):
    code: int
    message: str
    data: Json | None


class Response(typing.TypedDict):
    id: str
    result: Json | None
    error: ResponseError | None
    jsonrpc: str


class Request(typing.TypedDict):
    id: str
    method: str
    params: Json | None
    jsonrpc: str


class Notification(typing.TypedDict):
    method: str
    params: Json | None
    jsonrpc: str
