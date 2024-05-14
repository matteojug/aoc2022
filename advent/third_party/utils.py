# From: https://github.com/algorandlabs/smart-asa
#
# MIT License
#
# Copyright (c) 2022 Algorand
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import base64
from collections import namedtuple
from inspect import get_annotations
from typing import Union
from algosdk import constants
from algosdk import transaction
from algosdk.v2client import algod


def decode_state(state) -> dict[str, Union[int, bytes]]:
    return {
        # We are assuming that global space `key` are printable.
        # If that's not necessarily true, we can change that.
        base64.b64decode(s["key"]).decode(): base64.b64decode(s["value"]["bytes"])
        if s["value"]["type"] == 1
        else int(s["value"]["uint"])
        for s in state
    }


def get_global_state(
    algod_client: algod.AlgodClient, asc_idx: int
) -> dict[str, Union[bytes, int]]:
    global_state = algod_client.application_info(asc_idx)["params"]["global-state"]
    global_state = decode_state(global_state)
    return global_state


def get_local_state(
    algod_client: algod.AlgodClient, account_address: str, asc_idx: int
) -> dict[str, Union[bytes, int]]:
    local_states = algod_client.account_info(account_address)["apps-local-state"]
    local_state = [s for s in local_states if s["id"] == asc_idx][0].get(
        "key-value", {}
    )
    local_state = decode_state(local_state)
    return local_state


def get_params(
    algod_client: algod.AlgodClient, fee: int = None
) -> transaction.SuggestedParams:
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = fee or constants.MIN_TXN_FEE
    return params


def get_last_round(algod_client: algod.AlgodClient):
    return algod_client.status()["last-round"]


def get_last_timestamp(algod_client: algod.AlgodClient):
    return algod_client.block_info(get_last_round(algod_client))["block"]["ts"]


def assemble_program(algod_client: algod.AlgodClient, source_code: str) -> bytes:
    compile_response = algod_client.compile(source_code)
    return base64.b64decode(compile_response["result"])
