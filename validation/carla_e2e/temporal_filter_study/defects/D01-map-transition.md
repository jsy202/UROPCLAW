# D01 — Town03 지도 전환 중 서버 SIGSEGV

- 발견: Town10HD_Opt 파일럿200프레임 완료 후 client.load_world('Town03') 시 CARLA process exit139 / Signal11. 로그: ../carla_server.log. Town03 파일럿 영상0장.
- 증거: 서버 CommonUnixCrashHandler Signal11, 클라이언트 RPC timeout. 당시 클라이언트는 모델 로드·차량 spawn 이전 load_world 단계에 있었음.
- 원인 범위: CARLA/Unreal 지도 로딩 경로에서 발생. 세부 native 원인 또는 GPU OOM으로 단정할 증거 없음.
- 해결 시도: 대형 비최적화 지도 대신 동일 도로 지형의 Town03_Opt를 서버 시작 인자로 직접 선택. 성공 여부는 후속 파일럿에 기록.
- 평가 영향: 실패 파일럿은 dev/test에서 제외. 변경된 map identifier는 평가 수집 전에 protocol에 반영.

후속: Town03_Opt를 프로세스 시작 인자로 지정한 파일럿은200프레임/20초 완료,63검출,71/71actor정리. 본 실험은 두 지도 사이에서 서버를 새로 시작해 live load_world 경로를 회피한다. 원래 Town03과 Opt의 영상이 동일하다고 가정하지 않으며 결과 map명을 그대로 남긴다.

## 후속 원인 검증으로 바로잡은 내용
이배포본에서는실행인자로준Town03_Opt가적용되지않고기본Town10HD_Opt로시작하는것을직접RPC로확인했다. 앞선Town03_Opt파일럿은capture.py의명시적client.load_world에서성공한것이었다. 따라서시작인자자체가native충돌을해결했다는주장은철회한다. 검증된우회는새프로세스에서_Opt지도를명시적RPC로로드하는것이다. native SIGSEGV의세부원인은여전히모른다.

두번째지도재개시RPC에서Town10HD_Opt임을확인한뒤client.load_world('Town03_Opt')를호출했고,실제mapname확인후31번째녹화를시작했다. supervisor도명시적지도로드및로드후이름검증을하도록수정했다. test_server_readiness_loads_and_checks_actual_map 구현전실패/후통과. [CARLA0.9.13공식지도변경API](https://carla.readthedocs.io/en/0.9.13/core_map/#changing-the-map)를참고했다.
