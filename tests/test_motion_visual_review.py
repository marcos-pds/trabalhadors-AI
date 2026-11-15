import pytest

from central.motion_visual_review import VisualReviewError, review_scene


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {'candidates': [{'content': {'parts': [{'text': '{"status":"needs_revision","findings":["Porta diferente da imagem anterior"]}'}]}}]}


class FakeClient:
    def __init__(self):
        self.request = None

    def post(self, url, headers, json):
        self.request = (url, headers, json)
        return FakeResponse()


def test_visual_reviewer_compares_scene_master_and_previous_without_exposing_key():
    client = FakeClient()
    image = 'data:image/png;base64,aGVsbG8='
    result = review_scene(image, image, image, title='Corredor', action='A porta fecha',
                          visual_bible='Porta escura de madeira', api_key='secret-test', client=client)
    assert result['status'] == 'needs_revision'
    assert 'Porta' in result['findings'][0]
    url, headers, body = client.request
    assert url.endswith('gemini-3.1-flash-lite:generateContent')
    assert headers['x-goog-api-key'] == 'secret-test'
    assert len(body['contents'][0]['parts']) == 4
    assert 'secret-test' not in str(body)


def test_reviewer_does_not_require_a_character_in_an_empty_corridor():
    class MissingShadowClient(FakeClient):
        def post(self, url, headers, json):
            class Response(FakeResponse):
                def json(self):
                    return {'candidates': [{'content': {'parts': [{'text':
                        '{"status":"needs_revision","findings":["Falta a silhueta da Sombra"]}'}]}}]}
            return Response()
    image = 'data:image/png;base64,aGVsbG8='
    result = review_scene(image, image, None, title='Corredor vazio',
                          action='Camera moves forward in the empty hallway',
                          visual_bible='A Sombra aparece mais tarde.', api_key='secret-test',
                          client=MissingShadowClient())
    assert result['status'] == 'pass'
    assert result['findings'] == []


def test_visual_reviewer_rejects_invalid_image():
    with pytest.raises(VisualReviewError):
        review_scene('not-image', 'not-image', None, title='Cena', action='Andar',
                     visual_bible='', api_key='secret-test', client=FakeClient())
