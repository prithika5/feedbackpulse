from types import SimpleNamespace

import pipeline.label as label

GOOD = '{"name":"Forced Shuffle","description":"d","sentiment":"neg","keywords":["shuffle"]}'
BAD = GOOD.replace("Forced Shuffle", "Forced Shuffle and Unwanted Songs")


class FakeClient:
    """Returns the scripted answers in order and records each prompt."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        self.models = SimpleNamespace(generate_content=self.generate)

    def generate(self, model, contents, config):
        self.prompts.append(contents)
        return SimpleNamespace(text=self.answers.pop(0))


def use_fake(monkeypatch, client):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_MODEL", "fake-model")
    monkeypatch.setattr(label.genai, "Client", lambda **_: client)
    monkeypatch.setattr(label.time, "sleep", lambda _: None)


def test_invalid_label_is_retried_with_the_reason(monkeypatch, tmp_path):
    client = FakeClient([BAD, GOOD])
    use_fake(monkeypatch, client)
    assert label.label_cluster(["review"], cache_dir=tmp_path).name == "Forced Shuffle"
    assert client.prompts[0] != client.prompts[1]
    assert "2 to 4 words" in client.prompts[1]


def test_labels_are_cached_so_the_model_is_called_once(monkeypatch, tmp_path):
    client = FakeClient([GOOD])
    use_fake(monkeypatch, client)
    first = label.label_cluster(["review"], cache_dir=tmp_path)
    second = label.label_cluster(["review"], cache_dir=tmp_path)
    assert first == second
    assert len(client.prompts) == 1
