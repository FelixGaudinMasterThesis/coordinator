import json

def parse(filename):
    output = []
    with open(filename, "r") as file:
        for line in file.readlines():
            try:
                output.append(json.loads(line))
            except:
                pass
    return output
