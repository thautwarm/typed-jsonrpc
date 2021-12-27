from typing_extensions import Required
from typed_jsonrpc.jsonrpc import *
from typed_jsonrpc.msg_types import *
from typing import TypedDict

DocumentUri = str


class TextDocumentItem(TypedDict):
    uri: DocumentUri
    languageId: str
    version: int
    text: str


class DidOpenTextDocumentParams(TypedDict):
    textDocument: TextDocumentItem


lsp = LanguageServices()


@lsp.on_request("initialize")
# @lsp.on_notification("initialize")
def f(rpc: Rpc, req: Request):
    rpc.response(
        Response(
            jsonrpc=req["jsonrpc"],
            id=req["id"],
            result={
                "capabilities": {
                    "textDocumentSync": {"openClose": True, "change": 0, "save": {}},
                }
            },
            error=None,
        )
    )


@lsp.on_request("shutdown")
@lsp.on_notification("shutdown")
def shutdown(rpc: Rpc, y: Json):
    import sys

    sys.exit(0)


@lsp.on_request("textDocument/didOpen")
def g(rpc: Rpc, req: Request):
    params: Json = req["params"]
    text_document = params["textDocument"]
    n = Notification(
        jsonrpc=JSONRPC_VERSION,
        method="textDocument/publishDiagnostics",
        params={
            "uri": text_document["uri"],
            "diagnostics": [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 1, "character": 0},
                    },
                    "message": "Some very bad Python code",
                    "severity": 1,
                }
            ],
        },
    )
    print(n)
    rpc.notify(n)


run_rpc(lsp)
