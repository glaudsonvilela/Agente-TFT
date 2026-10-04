from remote_trainer.resources import ResourceSampler


def test_cgroup_and_host_usage_are_measured_between_refreshes(tmp_path):
    cgroup = tmp_path / 'cgroup'
    proc = tmp_path / 'proc'
    cgroup.mkdir()
    proc.mkdir()
    (cgroup / 'cpu.max').write_text('150000 100000\n')
    (cgroup / 'cpu.stat').write_text('usage_usec 1000000\n')
    (cgroup / 'memory.current').write_text(str(256 * 1024 * 1024))
    (cgroup / 'memory.max').write_text(str(1024 * 1024 * 1024))
    (proc / 'stat').write_text('cpu  100 0 100 800 0 0 0\n')
    (proc / 'meminfo').write_text('MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n')
    now = [10.0]
    sampler = ResourceSampler(cgroup=cgroup, proc=proc, clock=lambda: now[0])
    first = sampler.sample()
    assert first['container']['cpu_cores_used'] is None
    assert first['container']['memory_used_mib'] == 256
    assert first['host']['cpu_percent'] is None
    now[0] = 15.0
    (cgroup / 'cpu.stat').write_text('usage_usec 3500000\n')
    (proc / 'stat').write_text('cpu  200 0 200 1100 0 0 0\n')
    second = sampler.sample()
    assert second['container']['cpu_cores_used'] == 0.5
    assert second['container']['cpu_limit_cores'] == 1.5
    assert second['container']['cpu_percent_of_limit'] == 33.3
    assert second['container']['memory_percent_of_limit'] == 25.0
    assert second['host']['cpu_percent'] == 40.0


def test_missing_cgroup_metrics_are_reported_as_unavailable(tmp_path):
    sampler = ResourceSampler(cgroup=tmp_path / 'missing-cgroup',
                              proc=tmp_path / 'missing-proc', clock=lambda: 1.0)
    result = sampler.sample()
    assert result['container']['cpu_cores_used'] is None
    assert result['container']['memory_used_mib'] is None
    assert result['host']['cpu_percent'] is None
