import { DeviceDetailView } from '@/components/DeviceDetailView'

/**
 * Dynamic route: `/dashboard/devices/PC-7F42A91C`.
 * Next.js 15 delivers route params as a promise.
 */
export default async function DevicePage({
  params,
}: {
  params: Promise<{ deviceId: string }>
}) {
  const { deviceId } = await params
  return <DeviceDetailView deviceId={decodeURIComponent(deviceId).toUpperCase()} />
}