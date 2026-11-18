import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { getAuthOptions } from "@/lib/auth-options";

export const dynamic = "force-dynamic";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  if (process.env.NEXT_PUBLIC_DATA_MODE === "api") {
    const session = await getServerSession(getAuthOptions());
    if (!session?.accessToken || session.error) redirect("/api/auth/signin?callbackUrl=/admin");
    if (!session.roles.includes("admin")) redirect("/?access=denied");
  }
  return <>{children}</>;
}
