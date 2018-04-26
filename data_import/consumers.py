from channels.generic.websocket import WebsocketConsumer
import json

from data_import.models import Upload


class UploadConsumer(WebsocketConsumer):
    def connect(self):
        self.accept()

    def disconnect(self, close_code):
        pass

    def receive(self, text_data):
        text_json = json.loads(text_data)

        upload_queryset = Upload.objects.filter(id__in=text_json['upload_ids'])

        upload_dict = {}

        for u in upload_queryset:
            upload_dict[u.id] = u.standardized_file.get().processing

        self.send(text_data=json.dumps({
            'message': upload_dict
        }))
