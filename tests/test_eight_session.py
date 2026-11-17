import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

with patch.object(sys, "path", [str(Path(__file__).resolve().parents[1] / "podshift"), *sys.path]):
    from podshift.eight_client import EightPod
    from pyeight.eight import EightSleep, RequestError


class EightSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_uninitialized_pod_operations_fail_closed(self):
        pod = EightPod()
        for method, args in (
            (pod._read, ()),
            (pod._write_smart, ({},)),
            (pod._set_power, ("off",)),
            (pod._profile, ()),
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(SystemExit, "eight client is closed"):
                    await method(*args)

    async def test_closed_api_session_rejects_before_network(self):
        session = Mock(closed=True, request=AsyncMock())
        client = EightSleep("dev@example.invalid", "synthetic", "UTC", client_session=session)
        with self.assertRaisesRegex(RequestError, "Eight Sleep API session is closed"):
            await client.api_request("GET", "https://example.invalid")
        session.request.assert_not_awaited()
