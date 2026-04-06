from pydantic import BaseModel

from ..constants import GRPC


class RPCData(BaseModel):
    """
    Helper class containing necessary data for Google RPC calls.

    Parameters
    ----------
    rpcid : GRPC
        Google RPC ID.
    payload : str
        Payload for the RPC call.
    identifier : str, optional
        Identifier/order for the RPC call, defaults to "generic".
        Makes sense if there are multiple RPC calls in a batch, where this identifier
        can be used to distinguish between responses.
    """

    rpcid: GRPC
    payload: str
    identifier: str = "generic"

    def __repr__(self) -> str:
        return f"GRPC(rpcid={self.rpcid!r}, payload={self.payload!r}, identifier={self.identifier!r})"

    def serialize(self) -> list:
        """
        Serializes object into formatted payload ready for RPC call.
        """

        return [self.rpcid, self.payload, None, self.identifier]
