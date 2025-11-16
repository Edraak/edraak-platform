import json


class JSONSessionSerializer(object):
    def dumps(self, obj):
        return json.dumps(obj, separators=(",", ":")).encode("latin-1")

    def loads(self, data):
        return json.loads(data.decode("latin-1"))
