import app.services.outbox_handlers as outbox_handlers
from app.services.outbox_processor import _default_handlers


def test_outbox_default_handler_registry_contract() -> None:
    handlers = _default_handlers()

    assert isinstance(handlers, dict)
    assert handlers, "Default outbox handler registry must not be empty"

    for event_type, handler in handlers.items():
        assert isinstance(event_type, str), f"Event key must be str, got {type(event_type)}"
        assert callable(handler), f"{event_type} handler is not callable"

        handler_name = getattr(handler, "__name__", None)
        assert isinstance(handler_name, str) and handler_name, (
            f"{event_type} handler must have a valid __name__"
        )

        imported = getattr(outbox_handlers, handler_name)
        assert callable(imported), f"{event_type} handler {handler_name} is not callable when imported"
        assert imported is handler, (
            f"{event_type} registry handler {handler_name} does not match outbox_handlers.{handler_name}"
        )
