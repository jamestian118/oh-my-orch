from __future__ import annotations

import importlib
import runpy

from src.types.boundaries import APIResponse


def test_main_module_entrypoint_prints_expected_message(capsys) -> None:
    runpy.run_module("src.main", run_name="__main__")
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello from oh-my-orch"


def test_main_prints_expected_message(capsys) -> None:
    main_module = importlib.import_module("src.main")
    main_module.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello from oh-my-orch"


def test_api_response_defaults_data_to_none() -> None:
    response = APIResponse(status=200, message="ok")
    assert response.status == 200
    assert response.message == "ok"
    assert response.data is None


def test_api_response_accepts_payload_dict() -> None:
    payload = {"id": "123", "name": "omo"}
    response = APIResponse(status=201, message="created", data=payload)
    assert response.status == 201
    assert response.message == "created"
    assert response.data == payload
