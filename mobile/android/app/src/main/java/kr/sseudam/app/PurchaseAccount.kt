package kr.sseudam.app

/** 소유자 정보가 없는 예전 영수증도 최종 판단은 서버에서 한다. */
internal fun purchaseAccountMismatch(owner: String?, current: String?): Boolean =
    !owner.isNullOrBlank() && owner != current
