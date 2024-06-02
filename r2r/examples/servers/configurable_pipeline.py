import argparse
import os
import logging

from r2r import (
    R2RApp,
    R2RConfig,
    R2RPipeFactory,
    R2RPipelineFactory,
    R2RProviderFactory,
)

logger = logging.getLogger(__name__)

current_file_path = os.path.dirname(__file__)
configs_path = os.path.join(current_file_path, "..", "configs")

CONFIG_OPTIONS = {
    "default": None,
    "local_ollama": os.path.join(configs_path, "local_ollama.json"),
}

def r2r_app(config_name: str = "default"):
    if config_path := CONFIG_OPTIONS.get(config_name):
        logger.info(f"Using config path: {config_path}")
        config = R2RConfig.from_json(config_path)
    else:
        default_config_path = os.path.join(configs_path, "config.json")
        logger.info(f"Using default config path: {default_config_path}")
        config = R2RConfig.from_json(default_config_path)

    if config.embedding['provider'] == 'openai' and 'OPENAI_API_KEY' not in os.environ:
        raise ValueError("Must set OPENAI_API_KEY in order to initialize OpenAIEmbeddingProvider.")

    providers = R2RProviderFactory(config).create_providers()
    pipes = R2RPipeFactory(config, providers).create_pipes()
    pipelines = R2RPipelineFactory(config, pipes).create_pipelines()

    return R2RApp(
        config=config,
        providers=providers,
        pipelines=pipelines,
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="R2R Pipe")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to serve deployed pipe on.",
    )
    parser.add_argument(
        "--port",
        type=str,
        default="8000",
        help="Port to serve deployed pipe on.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="default",
        choices=CONFIG_OPTIONS.keys(),
        help="Configuration option for the pipe",
    )

    args, _ = parser.parse_known_args()

    host = os.getenv("HOST") or args.host
    port = os.getenv("PORT") or args.port
    config_name = os.getenv("CONFIG_OPTION") or args.config

    logger.info(f"Environment CONFIG_OPTION: {config_name}")

    r2r = r2r_app(config_name)
    app = r2r.app

    r2r.serve(host, int(port))
