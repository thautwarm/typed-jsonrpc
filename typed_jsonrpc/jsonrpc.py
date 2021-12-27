from __future__ import annotations
from asyncio.streams import StreamReader, StreamWriter
from collections import deque
from typed_jsonrpc.simple_async import Task, TaskException
from typed_jsonrpc import simple_async
from typed_jsonrpc.exceptions import *
from typed_jsonrpc.msg_types import *
import json
import sys
import uuid
import traceback
import logging
import typing
import asyncio

__all__ = ['ReceiveRequest', 'ReceiveNotify', 'LanguageServices', 'LSPServer', 'start_lsp_server', 'run_rpc', 'Rpc']
log = logging.getLogger(__name__)


ReceiveRequest = typing.Callable[["Rpc", Request], Task[None] | object]
ReceiveNotify = typing.Callable[["Rpc", Notification], None]


class LanguageServices:
    """JSON RPC service register
    """

    request_handlers: dict[str, ReceiveRequest]
    noftify_handlers: dict[str, ReceiveNotify]

    def __init__(self):
        self.request_handlers = {}
        self.noftify_handlers = {}

        @self.on_notification(CANCEL_METHOD)
        def cancel_request(rpc: Rpc, params: dict):
            rpc.cancel_task(params["id"])

    def on_request(self, item: str):
        def register(func):
            self.request_handlers[item] = func
            return func

        return register

    def on_notification(self, item: str):
        def register(func):
            self.noftify_handlers[item] = func
            return func

        return register


def _parse_lsp_head(line: bytes):
    """Extract the content length from an input line."""
    if line.startswith(b"Content-Length: "):
        _, value = line.split(b"Content-Length: ")
        value = value.strip()
        try:
            return int(value)
        except ValueError as e:
            raise ValueError("Invalid Content-Length header: {}".format(value)) from e

    return None


def _create_lsp_head(content_length: int):
    return (
        b"Content-Length: %d\r\n"
        b"Content-Type: application/vscode-jsonrpc; charset=utf8\r\n\r\n"
        % content_length
    )


class AsyncRequestHander:
    def __init__(
        self,
        reader: StreamReader,
        writer: StreamWriter,
        write_data_pack: deque[bytes],
        read_data_pack: deque[bytearray],
    ):
        self.reader = reader
        self.writer = writer
        self.write_data_pack: deque[bytes] = write_data_pack
        self.read_data_pack: deque[bytearray] = read_data_pack

    async def handle(self):
        await asyncio.gather(self.reading(), self.writing())

    async def reading(self):
        reader = self.reader
        while True:
            line = await reader.readline()
            log.warning("new json head:", line)
            if not line:
                continue
            content_length = _parse_lsp_head(line)

            if not content_length:
                continue
            
            # strip all other headers
            while line := (await reader.readline()):
                if line and line.strip():
                    continue
                break

            load = bytearray()
            left = content_length
            while left > 0:
                content = await reader.read(min(left, 1024))
                left -= len(content)
                load.extend(content)
            self.read_data_pack.append(load)

    async def writing(self):
        writer: asyncio.StreamWriter = self.writer
        while True:
            if not self.write_data_pack:
                await asyncio.sleep(0.05)
                continue
            data = self.write_data_pack.popleft()
            content_length = len(data)
            writer.write(_create_lsp_head(content_length))
            writer.write(data)
            await writer.drain()


class LSPServer:
    """do not create instance directly, use `start_lsp_server`.
    """
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.write_data_pack: deque[bytes] = deque()
        self.read_data_pack: deque[bytearray] = deque()

    async def listen(self):
        asrv = await asyncio.start_server(
            self._handle_request, self.host, int(self.port)
        )
        await asrv.serve_forever()

    async def _handle_request(self, reader: StreamReader, writer: StreamWriter):
        log.warning("new request")
        await AsyncRequestHander(
            reader, writer, self.write_data_pack, self.read_data_pack
        ).handle()

    def run(self, update_func):
        loop = asyncio.get_event_loop()
        try:
            old_run_once = getattr(loop, "_run_once")
        except AttributeError:
            raise TypeError("invalid event loop that cannot run real async code.")
        
        # safely hack python's async mechanism
        def _run_once():
            old_run_once()
            update_func()

        setattr(loop, "_run_once", _run_once)
        loop.run_until_complete(self.listen())


class Rpc:
    """do not create instance directly, this is available only when registering dispatches:
    >>> ls = LanguageServices()
    >>> ls.on_request("textDocument/didOpen")
    >>> def f(rpc: Rpc, params: Request):
    >>>   # do stuff
    """
    def __init__(self, md: LanguageServices, lsp_server: LSPServer):
        self.method_dispatcher = md
        self.lsp_server = lsp_server
        self.waiting_responses: dict[str, tuple[Json | None, Json | None] | None] = {}
        self.m_tasks: set[Task[typing.Any]] = set()
        self.task_to_ids: dict[Task[typing.Any], str] = {}
        self.id_to_tasks: dict[str, Task[typing.Any]] = {}

        def processing_messages():
            while True:
                if not lsp_server.read_data_pack:
                    yield
                    continue
                self.on_message(lsp_server.read_data_pack.popleft())
                yield

        self.m_tasks.add(processing_messages())

    def on_message(self, message: bytearray):
        try:
            self.receive(json.loads(message))
        except Exception as e:
            raise ValueError(f"fatal: dangerous LSP client message: {message}") from e

    def genid(self):
        return str(uuid.uuid4())

    def request(self, req: Request, error_handler=None):
        self.rawsend(req)
        identity = req["id"]
        while True:
            find = self.waiting_responses.get(identity)
            if find is None:
                yield
                continue
            (result, error) = find
            if error:
                if error_handler:
                    error_handler(error)
                else:
                    raise Exception(error)
                return
            return result

    def cancel_task(self, identity: str):
        if task := self.id_to_tasks.pop(identity, None):
            if simple_async.is_task(task):
                task.close()
                del self.task_to_ids[task]
                self.waiting_responses.pop(identity, None)

    def response(self, resp: Response):
        self.rawsend(resp)

    def notify(self, notify: Notification):
        self.rawsend(notify)

    def access_id_or_new_id(self, message):
        if isinstance(message, dict) and (identity := message.get("id")):
            return identity
        else:
            return self.genid()

    def senderror(self, id: str, error: ResponseError):
        self.rawsend(Response(jsonrpc=JSONRPC_VERSION, id=id, error=error, result=None))

    def receive(self, message: Response | Notification | Request):
        try:
            self._receive(message)
        except Exception:
            log.warning("Unknown error on msg: ", message)
            log.warning("trackback:", traceback.format_exc())

    def _receive(self, message: Response | Notification | Request):
        print(message)
        if "jsonrpc" not in message or message["jsonrpc"] != JSONRPC_VERSION:
            log.warning("Unknown message type %s", message)
            return

        if "id" not in message:
            notification = typing.cast(Notification, message)
            log.debug("Handling notification from client %s", notification)
            if handler := self.method_dispatcher.noftify_handlers.get(
                notification["method"]
            ):
                handler(self, notification)
            return

        elif "method" not in message:
            log.debug("Handling response from client %s", message)
            response = typing.cast(Response, message)
            self.waiting_responses[response["id"]] = (
                response.get("result"),
                typing.cast(Json, response.get("error")),
            )
            return

        log.debug("Handling request from client %s", message)
        request = typing.cast(Request, message)
        identity = request["id"]

        try:
            if handler := self.method_dispatcher.request_handlers.get(
                request["method"]
            ):
                request_result = handler(self, request)
                identity = request["id"]
                if simple_async.is_task(request_result):
                    task = typing.cast(Task[Response], request_result)
                    self.m_tasks.add(task)
                    self.task_to_ids[task] = identity
                    self.id_to_tasks[identity] = task
                    self.waiting_responses[identity] = None
                else:
                    result = typing.cast(Json, request_result)
                    if not isinstance(result, dict):
                        # do not send response
                        return

                    self.rawsend(
                        Response(
                            id=identity,
                            jsonrpc=request["jsonrpc"],
                            error=None,
                            result=result,
                        )
                    )
                return
        except JsonRpcException as e:
            log.exception("Failed to handle request %s", identity)
            self.senderror(identity, typing.cast(ResponseError, e.to_dict()))

        except Exception as e:
            identity = self.access_id_or_new_id(message)
            log.exception("Failed to handle request %s", identity)

            self.senderror(
                identity,
                typing.cast(
                    ResponseError, JsonRpcInternalError.of(sys.exc_info()).to_dict()
                ),
            )

    def rawsend(self, data: Response | Notification | Request):
        log.warning("sending messages, keys: ",  ','.join(data.keys()))
        datapack = json.dumps(data).encode("utf8")
        self.lsp_server.write_data_pack.append(datapack)

    def run_event_loop_step(self):
        try:
            completed_tasks = simple_async.run_once(self.m_tasks)
            for task in completed_tasks:
                identity = self.task_to_ids.pop(task, None)
                if identity is not None:
                    self.id_to_tasks.pop(identity, None)
                    self.waiting_responses.pop(identity, None)
        except TaskException as e:
            self.m_tasks.discard(e.task)
            log.warning("Unknown task error", traceback.format_exc())
        except Exception as e:
            log.warning("Unknown error", traceback.format_exc())


def start_lsp_server(host="127.0.0.1", port=8889):
    return LSPServer(host, port)

def run_rpc(md: LanguageServices, lsp_server: LSPServer | None = None):
    lsp_server = lsp_server or start_lsp_server()
    rpc = Rpc(md, lsp_server)
    lsp_server.run(rpc.run_event_loop_step)
