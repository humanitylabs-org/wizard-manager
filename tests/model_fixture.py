"""Explicit inference seam for legacy domain tests; never live evidence."""
from unittest.mock import patch
from manager import MODEL


def install_model_fixture(test):
    def factory(was, request):
        def infer(messages, max_tokens):
            response = request('http://model', {'model': MODEL, 'messages': messages, 'max_tokens': max_tokens})
            return response['choices'][0]['message']['content'], {
                'model': response['model'], 'label': 'Claude Sonnet', 'fallback': False}
        return infer
    mock = patch('manager.HermesInference', factory)
    mock.start()
    test.addCleanup(mock.stop)
