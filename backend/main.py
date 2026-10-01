# -*- coding: utf-8 -*-
"""Backend entrypoint: python backend/main.py [port]"""
import asyncio
import logging
import os
import sys

# Use HuggingFace mirror for China network (faster-whisper downloads models from HF)
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

# allow running both `python backend/main.py` and `python -m backend.main`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('main')


def main():
    from core.server import BackendServer
    from core.settings import load_config

    config = load_config()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(config.get('server', {}).get('port', 8765))

    server = BackendServer(port)

    logger.info('=' * 50)
    logger.info(' Desktop AI Girlfriend Backend')
    logger.info(' port           : %d', port)
    logger.info(' llm provider   : %s', server.llm.provider_name)
    logger.info(' stt model      : %s', config.get('stt', {}).get('model'))
    logger.info(' tts provider   : %s', server.tts.provider_name)
    logger.info('=' * 50)

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info('backend stopped by user')


if __name__ == '__main__':
    main()
