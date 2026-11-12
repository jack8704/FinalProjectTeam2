"""
서버 쪽 LLM 호출 (테스트·질의표준화·백업용)

실제 서비스 답변은 앱(Kotlin)이 서버가 준 prompt를 Gleo LLM SDK에 넣어 생성한다.
공급자 전환은 OpenAI SDK의 base_url·api_key만 바꾸는 방식 (수업 ch9_02~04)
  .env  LLM_PROVIDER=openai | upstage | ollama
"""
import os

import config


def chat(prompt: str, temperature: float = 0.1) -> str:
    from openai import OpenAI  # pip install openai

    spec = config.LLM_SPECS[config.LLM_PROVIDER]
    key = (
        os.getenv(spec["key_env"]) if spec["key_env"] else "ollama"
    )  # Ollama는 가짜 키여도 됨
    if not key:
        raise RuntimeError(f".env에 {spec['key_env']}가 없습니다. (서버 LLM은 선택 기능)")
    client = OpenAI(
        api_key=key,
        base_url=spec["base_url"],
        default_headers={"Accept-Encoding": "identity"},
    )  # 응답 압축 끔 (압축 해제 라이브러리 버전 충돌 회피)
    r = client.chat.completions.create(
        model=spec["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,  # 법률 안내 → 0~0.3 (일관성)
    )
    return r.choices[0].message.content.strip()


generate = chat  # 이전 코드 호환용 이름
