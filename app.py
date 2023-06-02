from flask import Flask, request, jsonify, redirect, url_for
from flask import Response
import os
import shutil
from werkzeug.utils import secure_filename
import string
import random
import threading
from datetime import datetime
from sjons_parser import parse
import json

sem = threading.Semaphore()

def mkdir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

qlogs_dir = "qlogs"
mkdir(qlogs_dir)
output_dir = "output"
mkdir(output_dir)
librespeed_qlogs_dir = "ls_qlogs"
mkdir(librespeed_qlogs_dir)
librespeed_proxy_acces = "proxy_acces.log"

caddy_qlogdir_indicator = "indicator"

with open(caddy_qlogdir_indicator, "w") as file:
    file.write("")

TEST_RUNNING=False
TEST_START_TIME=None
TEST_TYPE=None

TOKEN_SIZE = 20

def get_random_token():
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(TOKEN_SIZE))

def get_new_random_token(test_type):
    new_token = f"{test_type}_{get_random_token()}"
    if os.path.exists(os.path.join(output_dir, new_token)):
        return get_new_random_token(test_type)
    return new_token

app = Flask("Nesquic files")

# NesQUIC get server qlog
@app.route('/download/<path:filename>', methods=['GET'])
def download(filename):
    id = request.args.get('id')
    file = os.path.join(qlogs_dir, filename)
    if os.path.exists(file):
        with open(file) as f:
            content = f.read()
        if not id is None:
            # Save to id location
            c_dir = os.path.join(output_dir, secure_filename(id))
            if not os.path.exists(c_dir):
                return Response("Invalid ID", status=403)
            shutil.copy(file, c_dir)

        os.remove(file)
        return Response(content,
                    mimetype="text/plain",
                    headers={"Content-Disposition":
                             f"attachment;filename={filename}"})
    else:
        return Response("File not found ! ", status=404)

# NesQUIC upload client ZIP
# Releases lock
@app.route('/upload/<test_id>', methods=['POST', 'GET'])
def upload(test_id):
    global TEST_RUNNING
    global TEST_START_TIME
    global TEST_TYPE
    sem.acquire()
    TEST_RUNNING = None
    TEST_START_TIME = None
    TEST_TYPE = None
    sem.release()
    file = request.files["file"]
    c_dir = os.path.join(output_dir, secure_filename(test_id))
    if not os.path.exists(c_dir):
        return Response("Invalid ID", status=403)
    file.save(os.path.join(c_dir, secure_filename(file.filename)))
    return Response("Ok", status=200)

# (NesQUIC) or RPM ending
# Releases lock
@app.route('/release-lock/<test_id>', methods=["POST"])
def release(test_id):
    global TEST_RUNNING
    global TEST_START_TIME
    global TEST_TYPE
    sem.acquire()
    if TEST_RUNNING == test_id:
        if TEST_TYPE == "rpm":
            resp_msg = "Ok"
            # Qlog files TODO: Check
            # Change ext file to indicate caddy to generate file to dev/null
            with open(caddy_qlogdir_indicator, "w") as file:
                file.write("")
            try:
                with open(librespeed_proxy_acces) as logs:
                    with open(os.path.join(output_dir, secure_filename(test_id), "proxy.log"), "w") as out:
                        out.write(logs.read())
                        proxy_logs = parse(os.path.join(output_dir, secure_filename(test_id), "proxy.log"))
                        n_req = h3 = 0
                        for access in proxy_logs:
                            if access["request"]["method"] == "GET" or access["request"]["method"] == "POST":
                                if access["request"]["proto"] == "HTTP/3.0":
                                    h3 += 1
                                n_req += 1
                            resp_msg = f"{h3} of {n_req} request were made with HTTP/3"
            except Exception as err:
                print(f"Can't copy proxy file > {str(err)}")
            # Request body informations
            if request.data != None:
                with open(os.path.join(output_dir, secure_filename(test_id), "test.json"), "wb") as json_output:
                    json_output.write(request.data)
            print(request.get_json())
            TEST_RUNNING = None
            TEST_START_TIME = None
            TEST_TYPE = None
            sem.release()
            resp = Response(resp_msg, 200)
            resp.headers.add('Access-Control-Allow-Origin', '*')
            return resp
        elif TEST_TYPE == "nesquic":
            sem.release()
            return redirect(url_for("upload"))
        else:
            sem.release()
            return Response("Invalid test type ! Should not appear", 500)
    else:
        sem.release()
        return Response("Invalid token", 401)

test_timeout = {
    "nesquic" : 15,
    "rpm" : 2
}

# NesQUIC or RPM
# Gets lock
@app.route('/get-id', methods=['GET'])
def get_id():
    global TEST_RUNNING
    global TEST_START_TIME
    global TEST_TYPE
    new_test_type = request.args.get("type", "nesquic")
    
    resp = None
    sem.acquire()
    if TEST_RUNNING and ((datetime.now() - TEST_START_TIME).total_seconds() / 60) <= test_timeout.get(TEST_TYPE, 0):
        # Timeout after 15 min without response
        resp = Response("Another test is running", status=401)
    else:
        if new_test_type in test_timeout:
            new_id = get_new_random_token(new_test_type)
            TEST_RUNNING = new_id
            TEST_START_TIME = datetime.now()
            TEST_TYPE = new_test_type
            mkdir(os.path.join(output_dir, new_id))            
            if TEST_TYPE == "rpm":
                output_qlog = os.path.join(output_dir, new_id, "qlogs")
                mkdir(output_qlog)
                with open(caddy_qlogdir_indicator, "w") as file:
                    file.write(output_qlog)
                try:
                    # https://stackoverflow.com/questions/2769061/how-to-erase-the-file-contents-of-text-file-in-python
                    open(librespeed_proxy_acces, "w").close()
                    print("OK")
                except Exception as err:
                    print(f"Can't erase proxy file content > {str(err)}")
            resp = jsonify({
                'id' : new_id
            })
        else:
            resp = Response(f"Wrong test type: {new_test_type}", 400)

    sem.release()
    resp.headers.add('Access-Control-Allow-Origin', '*')
    return resp

if __name__ == "__main__":
    app.run()
