from arclith_cli.adapter_templates import render_container


def test_generated_container_logs_entity_repository_binding() -> None:
    rendered = render_container(
        "ChatThread",
        "chat_thread",
        ["mongodb"],
        {
            "application_import": "chat_service.application",
            "domain_import": "chat_service.domain",
            "adapters_import": "chat_service.adapters",
        },
    )

    assert (
        "adapter = arclith.config.adapters.repository_adapter_for(ChatThread)"
        in rendered
    )
    assert "adapter=adapter)" in rendered
