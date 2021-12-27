## typed-jsonrpc

Out-of-box Python RPC framework. **WIP.**

Make LSP easy for everyone.

The conception of final usage:

```python
from typed_jsonrpc import *

ls = LanguageServices()
@ls.on_request(METHOD.initialize)
def initialize_request(rpc: Rpc, params: Request):
    rpc.response(
        Response(
            jsonrpc=req["jsonrpc"],
            id=req["id"],
            error=None,
            result=MSG.InitializeResult(
                capabilities = MSG.ServerCapabilities(
                    textDocumentSync=MSG.TextDocumentSyncOptions(
                        MSG.TextDocumentSyncOptions(
                            openClose=True,
                            change=MSG.TextDocumentSyncKind.NONE
                        )
                    )
                )
            )
        )
    )
    
    resp: Response = yield from rpc.request(...)
    ...

lsp1 = start_lsp_server(host=..., port=...)
lsp2 = start_lsp_server(host=..., port=...)

simple_async.run_until_complete(
    simple_async.gather(
        run_lsp(ls, lsp1), run_lsp(ls, lsp2)))

```