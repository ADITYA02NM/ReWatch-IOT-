"""Bounded, offline reproductions of pre-publication security findings."""
import queue
from unittest.mock import Mock, patch

import pytest
import engine
import mailer
import rewatch as rw
from detector import AnomalyDetector
from iot import DevicePolicy, FirmwareMonitor
from summary import ReportWindow


def test_unknown_ids_cannot_starve_enrolled_anomaly_monitor():
    detector = AnomalyDetector(device_profiles={'safety': {'kind': 'sensor'}})
    for index in range(1024):
        detector.feed({'device': f'unknown-{index}', 'kind': 'sensor'}, 1)
    result = detector.feed({'device': 'safety', 'smoke': True}, 2)
    assert result and result['level'] == 'critical'
    assert len(detector.devices) <= 1024


def test_unknown_ids_cannot_starve_enrolled_firmware_monitor():
    monitor = FirmwareMonitor(DevicePolicy({'safety': {'approved_firmware': '1'}}))
    for index in range(1024):
        monitor.feed({'device': f'unknown-{index}', 'firmware': '1'}, 1)
    result = monitor.feed({'device': 'safety', 'firmware': '2'}, 2)
    assert result and result[0]['kind'] == 'firmware-change'
    assert len(monitor.versions) <= 1024


def test_mail_result_does_not_become_another_test_request():
    herald = mailer.Herald.__new__(mailer.Herald)
    herald.host, herald.port = 'smtp.invalid', 587
    herald.user = herald.password = herald.sender = herald.iface = ''
    herald.to, herald.sent, herald.last = [], set(), {}
    herald.dash = 'http://localhost'
    herald.q, herald.summary = queue.Queue(), ReportWindow()
    herald.bus = Mock()
    herald.on_msg(rw.topic('mail', 'test'), {'id': 'test'})
    kind, data = herald.q.get_nowait()
    herald.send(kind, data)
    topic, result = herald.bus.publish.call_args.args
    assert topic == rw.topic('mail', 'result', 'test')
    herald.on_msg(topic, result)
    assert herald.q.empty()


@pytest.mark.parametrize('source', ['1.2.3.4 }; flush ruleset; {', 'hostname', '', None, '::1'])
def test_nft_rejects_non_ipv4_and_command_syntax(source):
    with patch.dict('os.environ', {'RESPONDER_NFT': '1'}), patch.object(engine.subprocess, 'run') as run:
        assert engine.nft_block(source) is False
        run.assert_not_called()


def test_nft_passes_canonical_ipv4_only():
    with patch.dict('os.environ', {'RESPONDER_NFT': '1'}), patch.object(engine.subprocess, 'run') as run:
        assert engine.nft_block('192.0.2.5') is True
        assert run.call_args.args[0][-1] == '{ 192.0.2.5 }'
