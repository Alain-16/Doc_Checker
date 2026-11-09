import { Suspense } from "react";
import { AuthFrame } from "@/components/auth/auth-frame";
import { SetPassword } from "@/components/auth/set-password";

export default function Page() {
  return (
    <AuthFrame>
      <Suspense>
        <SetPassword purpose="reset" />
      </Suspense>
    </AuthFrame>
  );
}
