#!/usr/bin/env python3

import argparse
import sys
import os
import hmac
import hashlib
import json
import secrets
import subprocess
import struct
import time
import datetime

from flask import Flask, Response, abort, render_template, flash, request, session
from wtforms import Form, StringField, validators
from binascii import hexlify, unhexlify

from simple_hive_client.client import HiveException, HiveInterface, HiveRemoteBackend

from . import submit

class ReusableForm(Form):
    new_account_name = StringField('New Account Name:', validators=[validators.DataRequired()])


def require_server_security(conf):
    auth = conf.get("server_auth", {})
    username = auth.get("username") if isinstance(auth, dict) else None
    password = auth.get("password") if isinstance(auth, dict) else None
    session_secret = conf.get("session_secret")
    if not all(isinstance(value, str) and value for value in (
            username, password, session_secret)):
        raise RuntimeError(
            "server_auth username/password and session_secret are required"
        )
    return username, password, session_secret


def authorized(request_authorization, username, password):
    def equal(left, right):
        return hmac.compare_digest(
            (left or "").encode("utf-8"),
            (right or "").encode("utf-8"),
        )

    return bool(
        request_authorization
        and equal(request_authorization.username, username)
        and equal(request_authorization.password, password)
    )


def signature_from_result(result):
    if "error" in result:
        raise RuntimeError("transaction signer failed: {}".format(result["error"]))
    return result["result"]["sig"]


def hive_error_message(error):
    if error.args and isinstance(error.args[0], dict):
        cause = error.args[0].get("error")
        if isinstance(cause, dict) and cause.get("message"):
            return str(cause["message"])
        if cause:
            return str(cause)
    return str(error)

def main(argv):
    parser = argparse.ArgumentParser(prog=argv[0], description="Web Server")
    parser.add_argument("-c", "--conffile", default="server.conf", dest="conffile", metavar="FILE", help="Specify configuration file")
    parser.add_argument("--signer", default="sign_transaction", dest="sign_transaction_exe", metavar="FILE", help="Specify path to sign_transaction tool")
    parser.add_argument("--get-dev-key", default="get_dev_key", dest="get_dev_key_exe", metavar="FILE", help="Specify path to get_dev_key tool")
    parser.add_argument("-n", "--chain-name", default="", dest="chain_name", metavar="CN", help="Specify chain name")
    parser.add_argument("-cid", "--chain-id", default="", dest="chain_id", metavar="CID", help="Specify chain ID")
    parser.add_argument("--timeout", default=5.0, type=float, dest="timeout", metavar="SECONDS", help="API timeout")
    parser.add_argument("--read-retries", default=submit.DEFAULT_READ_RETRIES, type=int, dest="read_retries", metavar="COUNT", help="Retries for read-only Hive RPC calls")
    args = parser.parse_args(argv[1:])
    
    with open(args.conffile, "r") as f:
        conf = json.load(f)
    
    timeout = args.timeout
    
    node = conf["transaction_target"]["node"]
    shared_secret = conf["shared_secret"]
    account_creator = conf["account_creator"]
    auth_username, auth_password, session_secret = require_server_security(conf)
    result_bytes = subprocess.check_output([args.get_dev_key_exe, shared_secret, "active-" + account_creator])
    result_str = result_bytes.decode("utf-8")
    result_json = json.loads(result_str.strip())
    account_creator_wif = result_json[0]["private_key"]
    read_backend = HiveRemoteBackend(
        nodes=[node], appbase=True, min_timeout=timeout, max_timeout=timeout,
        max_retries=args.read_retries,
    )
    broadcast_backend = HiveRemoteBackend(
        nodes=[node], appbase=True, min_timeout=timeout, max_timeout=timeout,
        max_retries=0,
    )
    read_hived = HiveInterface(read_backend)
    broadcast_hived = HiveInterface(broadcast_backend)
    sign_transaction_exe = args.sign_transaction_exe
    
    if args.chain_name != "":
        chain_id = hashlib.sha256(str.encode(args.chain_name.strip())).digest().hex()
    else:
        chain_id = None

    if args.chain_id != "":
        chain_id = args.chain_id.strip()
    
    signer = submit.TransactionSigner(sign_transaction_exe=sign_transaction_exe, chain_id=chain_id)

    app = Flask(__name__)
    app.debug = bool(conf.get("debug", False))
    app.config['SECRET_KEY'] = session_secret

    @app.before_request
    def authenticate():
        if authorized(request.authorization, auth_username, auth_password):
            return None
        return Response(
            "Authentication required\n", 401,
            {"WWW-Authenticate": 'Basic realm="Tinman"'},
        )
 
    @app.route("/account_create", methods=['GET', 'POST'])
    def account_create():
        form = ReusableForm(request.form)
     
        print(form.errors)
        if request.method == 'POST':
            expected_csrf_token = session.get("csrf_token", "")
            submitted_csrf_token = request.form.get("csrf_token", "")
            if not expected_csrf_token or not hmac.compare_digest(
                    expected_csrf_token, submitted_csrf_token):
                abort(400, "invalid CSRF token")
            new_account_name = form.new_account_name.data
     
            if form.validate():
                key_types = ["owner", "active", "posting", "memo"]
                keys = {}
                
                for key_type in key_types:
                    result_bytes = subprocess.check_output([args.get_dev_key_exe, shared_secret, key_type + "-" + new_account_name])
                    result_str = result_bytes.decode("utf-8")
                    result_json = json.loads(result_str.strip())
                    
                    keys[key_type] = result_json[0]
                
                tx = {
                    "operations":[
                        {"type":"account_create_operation","value":{
                            "creator":account_creator,
                            "new_account_name":new_account_name,
                            "fee":{"amount":"0","nai":"@@000000021","precision":3},
                            "owner":{"account_auths":[["tnman",1]],"key_auths":[[keys["owner"]["public_key"],1]],"weight_threshold":1},
                            "active":{"account_auths":[["tnman",1]],"key_auths":[[keys["active"]["public_key"],1]],"weight_threshold":1},
                            "posting":{"account_auths":[["tnman",1]],"key_auths":[[keys["posting"]["public_key"],1]],"weight_threshold":1},
                            "memo_key":keys["memo"]["public_key"],
                            "json_metadata":""
                        }}, {"type":"transfer_to_vesting_operation","value":{
                            "amount":{"amount":"1000000","nai":"@@000000021","precision":3},
                            "from":account_creator,
                            "to":new_account_name
                        }}
                    ],
                    "signatures":[]
                }
                
                cached_dgpo = submit.CachedDgpo(hived=read_hived)
                dgpo = cached_dgpo.get()
                tx["ref_block_num"] = dgpo["head_block_number"] & 0xFFFF
                tx["ref_block_prefix"] = struct.unpack_from("<I", unhexlify(dgpo["head_block_id"]), 4)[0]
                head_block_time = datetime.datetime.strptime(dgpo["time"], "%Y-%m-%dT%H:%M:%S")
                expiration = head_block_time+datetime.timedelta(minutes=1)
                expiration_str = expiration.strftime("%Y-%m-%dT%H:%M:%S")
                tx["expiration"] = expiration_str

                result = signer.sign_transaction(tx, account_creator_wif)
                try:
                    tx["signatures"].append(signature_from_result(result))
                except RuntimeError as error:
                    flash("Unable to create account: " + str(error))
                    return render_template('account_create.html', form=form)
                
                print("bcast:", json.dumps(tx, separators=(",", ":")))
                
                try:
                    submit.broadcast_transaction(broadcast_hived, tx)
                    flash("Account Created: " + new_account_name)
                    
                    for key in keys:
                        flash(key + ": " + keys[key]["private_key"])
                except (HiveException, submit.BroadcastOutcomeUnknown) as e:
                    message = hive_error_message(e)
                    print(str(e))
                    flash("Unable to create account: " + message)
            else:
                flash('All the form fields are required.')
     
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return render_template('account_create.html', form=form)
    
    app.run(
        host=conf.get("host", "127.0.0.1"),
        port=int(conf.get("port", 5000)),
    )

if __name__ == "__main__":
    main(sys.argv)
