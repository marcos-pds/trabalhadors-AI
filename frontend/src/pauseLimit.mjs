export function pauseLimitKey(activity) {
  if (!activity?.run_id || activity.status !== 'paused_limit') return null
  // Each new checkpoint pause has a distinct run update timestamp. Repeated
  // polling of the same pause must not reopen a dismissed confirmation.
  return activity.run_id + ':' + (activity.updated_at || '')
}
