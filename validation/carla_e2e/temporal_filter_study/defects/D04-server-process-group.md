# D04 — 지도 전환 시 wrapper 종료와 실제 서버 종료의 차이

## 관측
Town10HD_Opt의30개 본실험은각1800프레임과actor정리를완료했다. 이후Town03_Opt서버시작이 `bind: Address already in use`로실패했다. 로그: batch_before_port_fix.log / server_Town03_Opt.log.

## 진단 근거
CarlaUE4.sh wrapper가종료됐는데Unreal child PID8252/PGID8232가계속살아있었고 `ss -ltnp`에서2000포트를점유했다. wrapper의 Popen.poll()만확인하고그룹종료를생략하거나자식종료전다음서버를시작한것이실험supervisor의문제였다. 앞선live load_world SIGSEGV와구분된다.

## 해결
직접시작해소유한프로세스그룹에SIGTERM을보내고RPC/streaming2000/2001/2002포트해제를확인한다.15초후에도점유하면해당소유그룹을SIGKILL하고다시해제확인후시작한다. 남아있던자식그룹도소유를확인해종료했다. 완료된30개는그대로보존하고나머지조건부터재개했다.

## 검증
`test_server_cleanup_signals_group_even_if_wrapper_already_exited`를추가해구현전실패/후통과.21studytests통과. 재개한batch가30개완료를건너뛰고Town03_Opt31번째조건을시작하는지후속로그로확인한다. 입력/YOLO/필터설정은변경하지않았다.
