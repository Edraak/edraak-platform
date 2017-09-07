from mock import Mock, patch


def mock_requests_get(status_code=200, body_json=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = body_json
    return patch('requests.get', return_value=response)
