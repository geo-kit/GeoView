"""Select the model used by GeoAgent before GeoView starts."""

import getpass
import json
import os
import sys
import urllib.request

PROVIDERS = {
    "lmstudio": {
        "label": "LM Studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "models_path": "/models",
        "base_env": ("LMSTUDIO_BASE_URL",),
        "key_env": (),
    },
    "ollama": {
        "label": "Ollama",
        "base_url": "http://127.0.0.1:11434",
        "models_path": "/api/tags",
        "base_env": ("OLLAMA_BASE_URL", "OLLAMA_HOST"),
        "key_env": (),
    },
    "gemini": {
        "label": "Google Gemini API",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models_path": "/models",
        "base_env": (),
        "key_env": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    },
    "openai": {
        "label": "OpenAI API",
        "base_url": "https://api.openai.com/v1",
        "models_path": "/models",
        "base_env": ("OPENAI_BASE_URL",),
        "key_env": ("OPENAI_API_KEY",),
    },
}


def _first(environment, names):
    return next((environment[name] for name in names if environment.get(name)), None)


def _choose(title, options, input_fn=input):
    print(f"{title}:\n")
    for number, option in enumerate(options, 1):
        print(f"{number}. {option}")

    while True:
        try:
            answer = input_fn("\nSelection: ").strip()
        except (EOFError, KeyboardInterrupt) as error:
            raise RuntimeError("GeoAgent setup was cancelled.") from error
        if answer in options:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("Enter an option number or exact value.")


def _list_models(provider, base_url, api_key, opener=urllib.request.urlopen):
    spec = PROVIDERS[provider]
    headers = {"Accept": "application/json"}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "gemini":
        headers["x-goog-api-key"] = api_key

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{spec['models_path']}", headers=headers
    )
    try:
        with opener(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Could not list models from {spec['label']} at {base_url}: {error}"
        ) from None

    if provider in ("lmstudio", "openai"):
        models = [item.get("id") for item in payload.get("data", [])]
    elif provider == "ollama":
        models = [item.get("name") for item in payload.get("models", [])]
    else:
        models = [
            item.get("name", "").removeprefix("models/")
            for item in payload.get("models", [])
            if "generateContent" in item.get("supportedGenerationMethods", [])
        ]
    return sorted({model for model in models if model})


def _select_model(models, input_fn):
    manual = "Enter model ID manually"
    selected = _choose("Available models", [*models, manual], input_fn)
    if selected != manual:
        return selected
    try:
        model = input_fn("Model ID: ").strip()
    except (EOFError, KeyboardInterrupt) as error:
        raise RuntimeError("GeoAgent setup was cancelled.") from error
    if not model:
        raise RuntimeError("Model ID cannot be empty.")
    return model


def configure_agent(
    args,
    *,
    environ=None,
    interactive=None,
    input_fn=input,
    opener=urllib.request.urlopen,
):
    """Return the qualified model name and environment for the child process."""
    environment = os.environ if environ is None else environ
    interactive = sys.stdin.isatty() if interactive is None else interactive

    provider = getattr(args, "agent_provider", None) or environment.get(
        "GEOVIEW_AGENT_PROVIDER"
    )
    if not provider:
        if not interactive:
            raise RuntimeError("Non-interactive launch requires --agent-provider.")
        label = _choose(
            "Select model provider",
            [spec["label"] for spec in PROVIDERS.values()],
            input_fn,
        )
        provider = next(
            name for name, spec in PROVIDERS.items() if spec["label"] == label
        )
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise RuntimeError(f"Unknown model provider: {provider}")

    spec = PROVIDERS[provider]
    base_url = (
        getattr(args, "agent_base_url", None)
        or environment.get("GEOVIEW_AGENT_BASE_URL")
        or _first(environment, spec["base_env"])
        or spec["base_url"]
    ).rstrip("/")
    model = (
        getattr(args, "agent_model", None)
        or environment.get("GEOVIEW_AGENT_MODEL")
    )

    api_key = _first(environment, spec["key_env"])
    if spec["key_env"] and not api_key:
        if not interactive:
            raise RuntimeError(
                f"{spec['label']} requires {spec['key_env'][0]} in the environment."
            )
        api_key = getpass.getpass(f"{spec['key_env'][0]}: ").strip()
        if not api_key:
            raise RuntimeError("API key cannot be empty.")

    if not model:
        if not interactive:
            raise RuntimeError("Non-interactive launch requires --agent-model.")
        entered_url = input_fn(f"{spec['label']} endpoint [{base_url}]: ").strip()
        base_url = entered_url.rstrip("/") or base_url
        model = _select_model(
            _list_models(provider, base_url, api_key, opener), input_fn
        )

    child_environment = dict(environment)
    if spec["base_env"]:
        child_environment[spec["base_env"][0]] = base_url
    if provider == "lmstudio":
        child_environment["LMSTUDIO_MODEL"] = model
    if api_key:
        child_environment[spec["key_env"][0]] = api_key

    return f"{provider}:{model}", child_environment
