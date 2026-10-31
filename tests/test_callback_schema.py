"""Archive compatibility accepts schema 7/8; older and unknown fail closed."""
import unittest
from types import SimpleNamespace
from app.main import ready


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class Connection:
    def __init__(self, revision):
        self.revision = revision

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, statement):
        sql = str(statement)
        if 'alembic_version' in sql:
            return Result(self.revision)
        if 'environment_metadata' in sql:
            return Result('staging')
        return Result(None)


class CallbackSchemaTests(unittest.TestCase):
    def test_readiness_requires_current_schema(self):
        for revision in ['0004_campaigns', '0005_calendar', '0006_callbacks', '0007_voice', '0008_recordings', '9999_unknown']:
            with self.subTest(revision=revision):
                engine = SimpleNamespace(connect=lambda: Connection(revision))
                request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))
                result = ready(request)
                if revision not in {'0007_voice','0008_recordings'}:
                    self.assertEqual(result.status_code, 503)
                else:
                    self.assertEqual(result['status'], 'ready')
                    self.assertEqual(result['migration'], revision)
