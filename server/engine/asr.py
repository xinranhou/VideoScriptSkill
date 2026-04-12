"""腾讯云 ASR 调用模块"""

import base64
import logging
import time
from pathlib import Path

from tencentcloud.asr.v20190614 import models as AsrModels
from tencentcloud.asr.v20190614.asr_client import AsrClient
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

from ..config import get_asr_config, get_tencent_creds

logger = logging.getLogger(__name__)


def build_client() -> AsrClient:
    """构建腾讯云 ASR 客户端"""
    creds = get_tencent_creds()
    http_profile = HttpProfile()
    http_profile.endpoint = "asr.ap-guangzhou.tencentcloudapi.com"
    http_profile.reqTimeout = 90
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    return AsrClient(
        credential.Credential(creds["secret_id"], creds["secret_key"]),
        creds["region"],
        client_profile,
    )


def recognize_chunk(
    client: AsrClient,
    chunk_path: Path,
    chunk_idx: int,
) -> str | None:
    """
    识别单个音频切片。

    Returns:
        识别文本，失败返回 None
    """
    cfg = get_asr_config()

    with open(chunk_path, "rb") as f:
        data = f.read()
    b64_data = base64.b64encode(data).decode()

    req = AsrModels.SentenceRecognitionRequest()
    req.EngSerViceType = cfg.get("engine", "16k_zh")
    req.SourceType = 1
    req.VoiceFormat = cfg.get("voice_format", "wav")
    req.Data = b64_data
    req.DataLen = len(data)

    max_retries = cfg.get("max_retries", 3)
    base_delay = cfg.get("retry_base_delay", 3)

    for attempt in range(1, max_retries + 1):
        try:
            resp = client.SentenceRecognition(req)
            return resp.Result
        except TencentCloudSDKException as e:
            logger.warning(f"片段 {chunk_idx} 第 {attempt} 次重试失败: {e}")
            if attempt < max_retries:
                time.sleep(base_delay * attempt)
        except Exception as e:
            logger.warning(f"片段 {chunk_idx} 第 {attempt} 次意外错误: {e}")
            if attempt < max_retries:
                time.sleep(base_delay * attempt)

    return None


def recognize_all(
    chunks: list,
    progress_callback=None,
) -> dict[int, str | None]:
    """
    逐个识别所有切片（单线程强制顺序）。

    Args:
        chunks: Chunk 对象列表
        progress_callback: (idx, total, result) -> None，每完成一片调用一次

    Returns:
        {chunk_index: result_text or None}
    """
    client = build_client()
    cfg = get_asr_config()
    batch_size = cfg.get("batch_size", 10)
    batch_sleep = cfg.get("batch_sleep_seconds", 2)

    results: dict[int, str | None] = {}

    for i, chunk in enumerate(chunks):
        result = recognize_chunk(client, chunk.path, i + 1)
        results[chunk.index] = result

        if progress_callback:
            progress_callback(i + 1, len(chunks), result, chunk)

        # 每 batch_size 片段强制休眠，防止 API 限流
        if (i + 1) % batch_size == 0:
            logger.debug(f"已完成 {i + 1} 片段，休眠 {batch_sleep} 秒")
            time.sleep(batch_sleep)

    return results
