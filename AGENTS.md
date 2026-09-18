# 프로젝트 작업 안내

<!-- wikwik:docs-guide:start -->
## 문서 우선

이 프로젝트의 요구사항·계획·결정·구조·과거 교훈은 `docs/`가 단일 출처다. 작업 전에 아래 시작점에서 관련 인덱스를 먼저 읽고, 인덱스가 가리키는 필요한 본문만 따라간다. 코드만 보고 문서화된 의도를 추측하거나 `docs/` 전체를 전수 읽지 않는다.

| 문서 영역 | 역할 | 먼저 읽을 시작점 |
|---|---|---|
| `docs/architecture/` | 사전 설계와 사후 구현 구조·계약·운영 문서 | [docs/architecture/architecture.md](<docs/architecture/architecture.md>) |
| `docs/plans/` | 구현 계획과 task | [docs/plans/plans-index.md](<docs/plans/plans-index.md>) |
| `docs/spec/` | 기능 요구사항·설계 spec | [docs/spec/spec-index.md](<docs/spec/spec-index.md>) |

`docs/` 루트 문서: [docs/product.md](<docs/product.md>)

인덱스가 없는 영역은 자동으로 전수 탐색하지 않는다. 필요한 문서를 좁혀 확인하고, 지속적으로 쓰는 영역이면 해당 영역의 인덱스를 먼저 만든다.

architecture 공통 색인에서 같은 주제·파일명의 `design/`(`status: design`)과 `as-built/`(`status: as-built`) 문서 및 반영 범위를 찾는다. 변경 없는 주제의 현재 구조는 사후 MD와 코드로 확인하고 design을 다시 읽지 않는다. 신규·변경 영역은 as-built 존재와 관계없이 승인 spec·ADR이 채택한 design을 목표로 함께 읽는다. 진행 중 계획은 plan에 고정한 설계 입력의 시점을 따른다. 사후 MD가 없으면 design을 목표 참고로 읽되 현재 구현은 코드에서 확인한다.

추가·수정 개발의 brain은 요구 합의 전에, make-plans·execute-dev·debug-dev는 대상 기능·Task·이슈가 정해진 뒤 architecture 색인에 연결된 사후 `as-built/01-project-structure.md`를 읽는다. 실제 폴더·진입점과 `File Responsibility Map`으로 현재 구조·책임·관련 파일을 좁히고, 연결된 관련 사후 문서와 실제 코드·직접 의존 관계·관련 테스트를 필요한 범위만 확인한다. 색인·사후 문서·표·관련 행이 없거나 코드와 다르면 해당 기능을 코드에서 좁게 확인하고 누락·차이를 후속 sync에 넘긴다. 문서와 표만으로 구현 사실이나 수정 범위를 확정하지 않는다.

brain은 design을 최신 승인 목표로 갱신한다. sync·migration의 공용 architecture 게이트는 design을 수정하지 않고 코드를 실측해 as-built와 파일 책임표를 작성·갱신한다. as-built는 design을 구현 근거로 사용하지 않으며 실측으로 동일함을 확인한 내용만 복사할 수 있다. 문서의 짝이 있어도 전체 구현 완료를 뜻하지 않는다. 공통 색인의 미반영·부분 반영·반영 완료는 적용 영역과 실측 기준으로 판단한다.

사후 MD의 `applicability: inactive`와 색인의 `현재 적용 안 함`은 해당 역할·영역의 적용 종료를 뜻한다. design에서 제외된 목표와 코드에서 실제 제거된 범위를 구분하며, 아직 구현하지 않은 설계를 코드 부재만으로 종료하지 않는다.

구현 사실의 정본은 검증된 코드다. 코드와 docs가 어긋나면 어느 한쪽을 조용히 가정하지 말고 차이를 드러내며 동기화가 필요하다고 알린다.
<!-- wikwik:docs-guide:end -->
