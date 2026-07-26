from __future__ import annotations

import pytest

from computer_use_agent.discovery_adapters import (
    DEFAULT_DISCOVERY_ADAPTERS,
    DISCOVERY_ADAPTERS,
    MAX_DISCOVERY_IDENTITIES_PER_PASS,
    MAX_DISCOVERY_SNAPSHOT_CHARS,
    MAX_DISCOVERY_SNAPSHOT_LINES,
    DiscoveryAdapter,
    DiscoveryAdapterError,
    DiscoveryAdapterRegistry,
    discovery_adapter_for_kind,
    discovery_adapter_policy_digest,
    discovery_adapter_schema_digest,
    discovery_source_digest,
    parse_discovery_identities,
)


LINK_ADAPTER = discovery_adapter_for_kind("boss_saved_job_review")
CONTROL_ADAPTER = discovery_adapter_for_kind("enterprise_incident")


def _link_line(
    public_id: str,
    *,
    role: str = "link",
    marker: str = "personal_interest_brand",
    host: str = "www.zhipin.com",
    scheme: str = "https",
) -> str:
    url = f"{scheme}://{host}/job_detail/{public_id}.html?ka={marker}&securityId=discard-me"
    return f'ref_1 | {role} "Role at Private Company" | (1,2,3,4) | enabled | value="{url}"'


def _control_lines(*public_ids: str, marker: str = "Incident queue - open") -> str:
    header = f'ref_1 | text "{marker}" | (0,0,10,10) | enabled'
    rows = [
        f'ref_{index} | listitem "{public_id} Printer offline" | (0,0,10,10) | enabled'
        for index, public_id in enumerate(public_ids, start=2)
    ]
    return "\n".join([header, *rows])


def test_registry_exposes_only_reviewed_kinds() -> None:
    assert DEFAULT_DISCOVERY_ADAPTERS.kinds == (
        "boss_saved_job_review",
        "enterprise_incident",
    )
    assert len(DISCOVERY_ADAPTERS) == len(DEFAULT_DISCOVERY_ADAPTERS.kinds)


def test_registry_refuses_unregistered_kind() -> None:
    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_ADAPTER_UNSUPPORTED"):
        discovery_adapter_for_kind("google_docs_section_review")


def test_registry_refuses_duplicate_kinds() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DiscoveryAdapterRegistry((LINK_ADAPTER, LINK_ADAPTER))


def test_registry_refuses_adapter_without_reviewed_scenario() -> None:
    unknown_kind = DiscoveryAdapter(
        adapter_id="unknown_kind",
        campaign_kind="not_a_reviewed_kind",
        identity_dimension="public_job_id",
        mode="control_name",
        item_key_prefix="x",
        identity_pattern=r"(ITEM-[0-9]{4})",
        source_marker_pattern=r"Queue",
        roles=("listitem",),
    )
    unknown_dimension = DiscoveryAdapter(
        adapter_id="unknown_dimension",
        campaign_kind="enterprise_incident",
        identity_dimension="not_an_identity_dimension",
        mode="control_name",
        item_key_prefix="x",
        identity_pattern=r"(ITEM-[0-9]{4})",
        source_marker_pattern=r"Queue",
        roles=("listitem",),
    )
    for adapter in (unknown_kind, unknown_dimension):
        with pytest.raises(ValueError, match="reviewed scenario"):
            DiscoveryAdapterRegistry((adapter,))


@pytest.mark.parametrize(
    "changes",
    [
        {"adapter_id": "Not Lower"},
        {"mode": "screenshot_pixels"},
        {"item_key_prefix": "Bad Prefix"},
        {"identity_pattern": r"/job_detail/[A-Za-z0-9]+\.html"},
        {"identity_pattern": r"/job_detail/([A-Za-z0-9]+)/([0-9]+)\.html"},
        {"identity_pattern": "("},
        {"source_marker_pattern": r"(personal_interest_brand)"},
        {"roles": ()},
        {"roles": ("link", "link")},
        {"roles": ("window",)},
        {"hosts": ()},
        {"hosts": ("Not A Host",)},
        {"marker_query_key": None},
        {"marker_query_key": "not a key"},
    ],
)
def test_adapter_validation_fails_closed(changes: dict[str, object]) -> None:
    fields = {
        "adapter_id": LINK_ADAPTER.adapter_id,
        "campaign_kind": LINK_ADAPTER.campaign_kind,
        "identity_dimension": LINK_ADAPTER.identity_dimension,
        "mode": LINK_ADAPTER.mode,
        "item_key_prefix": LINK_ADAPTER.item_key_prefix,
        "identity_pattern": LINK_ADAPTER.identity_pattern,
        "source_marker_pattern": LINK_ADAPTER.source_marker_pattern,
        "roles": LINK_ADAPTER.roles,
        "hosts": LINK_ADAPTER.hosts,
        "marker_query_key": LINK_ADAPTER.marker_query_key,
    }
    fields.update(changes)

    with pytest.raises(ValueError):
        DiscoveryAdapter(**fields)  # type: ignore[arg-type]


def test_control_adapter_cannot_bind_url_fields() -> None:
    with pytest.raises(ValueError, match="URL fields"):
        DiscoveryAdapter(
            adapter_id="control_with_host",
            campaign_kind="enterprise_incident",
            identity_dimension="ticket_id",
            mode="control_name",
            item_key_prefix="incident:ticket",
            identity_pattern=r"(INC-[0-9]{4,12})",
            source_marker_pattern=r"Incident queue",
            roles=("listitem",),
            hosts=("example.com",),
        )


def test_link_mode_extracts_unique_ids_and_discards_url_fields() -> None:
    snapshot = "\n".join(
        [
            _link_line("publicjob001"),
            _link_line("publicjob002", role="hyperlink"),
            _link_line("publicjob001"),
        ]
    )

    identities = parse_discovery_identities(LINK_ADAPTER, snapshot)

    assert [identity.item_key for identity in identities] == [
        "boss:job:publicjob001",
        "boss:job:publicjob002",
    ]
    assert all("securityId" not in identity.item_key for identity in identities)


def test_link_mode_accepts_a_page_level_source_marker() -> None:
    snapshot = "\n".join(
        [
            'ref_1 | hyperlink "Company" | (1,2,3,4) | enabled '
            '| value="https://www.zhipin.com/gongsi/example~~.html'
            '?ka=personal_interest_brand_45171c7ac"',
            'ref_2 | hyperlink "Role" | (1,2,3,4) | enabled '
            '| value="https://www.zhipin.com/job_detail/publicjob001.html'
            '?securityId=discard-me"',
        ]
    )

    identities = parse_discovery_identities(LINK_ADAPTER, snapshot)

    assert [identity.item_key for identity in identities] == ["boss:job:publicjob001"]


@pytest.mark.parametrize(
    "line",
    [
        _link_line("publicjob001", marker="other_source"),
        _link_line("publicjob001", host="jobs.example.com"),
        _link_line("publicjob001", scheme="http"),
        _link_line("publicjob001", role="button"),
        'ref_1 | link "Role" | (1,2,3,4) | enabled '
        '| value="https://user:pass@www.zhipin.com/job_detail/publicjob001.html'
        '?ka=personal_interest_brand"',
        'ref_1 | link "Role" | (1,2,3,4) | enabled '
        '| value="https://www.zhipin.com:8443/job_detail/publicjob001.html'
        '?ka=personal_interest_brand"',
    ],
)
def test_link_mode_requires_the_exact_reviewed_source(line: str) -> None:
    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_SOURCE_MARKER_ABSENT"):
        parse_discovery_identities(LINK_ADAPTER, line)


def test_link_mode_reports_no_identities_when_only_the_marker_is_present() -> None:
    snapshot = (
        'ref_1 | hyperlink "Company" | (1,2,3,4) | enabled '
        '| value="https://www.zhipin.com/gongsi/example~~.html'
        '?ka=personal_interest_brand"'
    )

    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_NO_IDENTITIES"):
        parse_discovery_identities(LINK_ADAPTER, snapshot)


def test_control_mode_extracts_only_allowed_roles() -> None:
    snapshot = "\n".join(
        [
            'ref_1 | text "Incident queue - open" | (0,0,10,10) | enabled',
            'ref_2 | listitem "INC-004821 Printer offline" | (0,0,10,10) | enabled',
            'ref_3 | dataitem "INC-004822 VPN degraded" | (0,0,10,10) | enabled',
            'ref_4 | button "INC-004823 Refresh" | (0,0,10,10) | enabled',
            'ref_5 | listitem "INC-004821 Printer offline" | (0,0,10,10) | enabled',
        ]
    )

    identities = parse_discovery_identities(CONTROL_ADAPTER, snapshot)

    assert [identity.item_key for identity in identities] == [
        "incident:ticket:INC-004821",
        "incident:ticket:INC-004822",
    ]


def test_control_mode_requires_the_source_marker() -> None:
    snapshot = 'ref_2 | listitem "INC-004821 Printer offline" | (0,0,10,10) | enabled'

    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_SOURCE_MARKER_ABSENT"):
        parse_discovery_identities(CONTROL_ADAPTER, snapshot)


def test_control_mode_ignores_rows_without_a_stable_identity() -> None:
    snapshot = "\n".join(
        [
            'ref_1 | text "Incident queue - open" | (0,0,10,10) | enabled',
            'ref_2 | listitem "Unassigned request" | (0,0,10,10) | enabled',
        ]
    )

    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_NO_IDENTITIES"):
        parse_discovery_identities(CONTROL_ADAPTER, snapshot)


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        pytest.param("", "DISCOVERY_SNAPSHOT_INVALID", id="empty"),
        pytest.param(
            "x" * (MAX_DISCOVERY_SNAPSHOT_CHARS + 1),
            "DISCOVERY_SNAPSHOT_TOO_LARGE",
            id="too-many-chars",
        ),
        pytest.param(
            "\n".join(["x"] * (MAX_DISCOVERY_SNAPSHOT_LINES + 1)),
            "DISCOVERY_SNAPSHOT_TOO_LARGE",
            id="too-many-lines",
        ),
        pytest.param(
            _link_line("publicjob001") + "\n# … 12 more truncated — narrow with find()",
            "DISCOVERY_SNAPSHOT_INCOMPLETE",
            id="truncated",
        ),
        pytest.param(
            _link_line("publicjob001") + "\n# incomplete: content may still be loading",
            "DISCOVERY_SNAPSHOT_INCOMPLETE",
            id="incomplete",
        ),
    ],
)
def test_bounded_observation_is_enforced(snapshot: str, code: str) -> None:
    with pytest.raises(DiscoveryAdapterError, match=code):
        parse_discovery_identities(LINK_ADAPTER, snapshot)


def test_too_many_identities_in_one_pass_fails_closed() -> None:
    snapshot = _control_lines(
        *(f"INC-{index:06d}" for index in range(MAX_DISCOVERY_IDENTITIES_PER_PASS + 1))
    )

    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_TOO_MANY_IDENTITIES"):
        parse_discovery_identities(CONTROL_ADAPTER, snapshot)


def test_maximum_identities_in_one_pass_is_accepted() -> None:
    snapshot = _control_lines(
        *(f"INC-{index:06d}" for index in range(MAX_DISCOVERY_IDENTITIES_PER_PASS))
    )

    identities = parse_discovery_identities(CONTROL_ADAPTER, snapshot)

    assert len(identities) == MAX_DISCOVERY_IDENTITIES_PER_PASS


def test_parse_refuses_a_non_adapter() -> None:
    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_ADAPTER_INVALID"):
        parse_discovery_identities("boss_saved_job_review", _link_line("publicjob001"))  # type: ignore[arg-type]


def test_source_digest_changes_with_observed_text() -> None:
    first = discovery_source_digest(_link_line("publicjob001"))
    second = discovery_source_digest(_link_line("publicjob002"))

    assert first != second
    assert first == discovery_source_digest(_link_line("publicjob001"))
    with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_SNAPSHOT_INVALID"):
        discovery_source_digest("")


def test_digests_bind_extraction_and_persistence_facts() -> None:
    widened = DiscoveryAdapter(
        adapter_id=LINK_ADAPTER.adapter_id,
        campaign_kind=LINK_ADAPTER.campaign_kind,
        identity_dimension=LINK_ADAPTER.identity_dimension,
        mode=LINK_ADAPTER.mode,
        item_key_prefix=LINK_ADAPTER.item_key_prefix,
        identity_pattern=LINK_ADAPTER.identity_pattern,
        source_marker_pattern=LINK_ADAPTER.source_marker_pattern,
        roles=LINK_ADAPTER.roles + ("button",),
        hosts=LINK_ADAPTER.hosts,
        marker_query_key=LINK_ADAPTER.marker_query_key,
    )
    reprefixed = DiscoveryAdapter(
        adapter_id=LINK_ADAPTER.adapter_id,
        campaign_kind=LINK_ADAPTER.campaign_kind,
        identity_dimension=LINK_ADAPTER.identity_dimension,
        mode=LINK_ADAPTER.mode,
        item_key_prefix="boss:posting",
        identity_pattern=LINK_ADAPTER.identity_pattern,
        source_marker_pattern=LINK_ADAPTER.source_marker_pattern,
        roles=LINK_ADAPTER.roles,
        hosts=LINK_ADAPTER.hosts,
        marker_query_key=LINK_ADAPTER.marker_query_key,
    )

    assert discovery_adapter_policy_digest(widened) != discovery_adapter_policy_digest(
        LINK_ADAPTER
    )
    assert discovery_adapter_schema_digest(widened) == discovery_adapter_schema_digest(
        LINK_ADAPTER
    )
    assert discovery_adapter_schema_digest(reprefixed) != discovery_adapter_schema_digest(
        LINK_ADAPTER
    )
    for digest in (discovery_adapter_policy_digest, discovery_adapter_schema_digest):
        with pytest.raises(DiscoveryAdapterError, match="DISCOVERY_ADAPTER_INVALID"):
            digest("boss_saved_job_links")  # type: ignore[arg-type]
