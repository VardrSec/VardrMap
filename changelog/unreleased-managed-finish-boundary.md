# Managed finalization boundary

Managed claims now refuse all legacy execution-finish outcomes, including failure,
cancellation and uncertainty. This preserves capacity, contract consumption and
receipt state until the exact managed result or known-stop protocol completes.
The regression covers both managed markers, consumed and unconsumed contracts,
and every legacy finish outcome. Ordinary legacy finalization is unchanged.
