"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getMe } from "@/lib/api/client";
import { useAuthStore } from "@/lib/stores/auth";

const schema = z.object({
  apiUrl: z.string().url("Podaj poprawny URL API"),
  apiKey: z.string().min(10, "API key jest wymagany"),
});

type SetupForm = z.infer<typeof schema>;

export default function SetupPage(): React.JSX.Element {
  const router = useRouter();
  const { hydrate, hydrated, apiKey, setCredentials, setUser } = useAuthStore();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (hydrated && apiKey) {
      router.replace("/");
    }
  }, [apiKey, hydrated, router]);

  const form = useForm<SetupForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      apiUrl: "http://localhost:8000",
      apiKey: "",
    },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      setCredentials(values.apiKey, values.apiUrl);
      const me = await getMe();
      setUser({
        id: me.id,
        username: me.username,
        email: me.email,
        role: me.role,
      });
      toast.success("Połączono z API");
      router.replace("/");
    } catch {
      useAuthStore.getState().clear();
      toast.error("Nie udało się połączyć. Sprawdź API URL i API key.");
    }
  });

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-100 p-6">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>Etanetas — pierwsze uruchomienie</CardTitle>
          <CardDescription>Skonfiguruj połączenie z backendem FastAPI.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="apiUrl">API URL</Label>
              <Input id="apiUrl" placeholder="http://localhost:8000" {...form.register("apiUrl")} />
              {form.formState.errors.apiUrl ? (
                <p className="text-xs text-red-600">{form.formState.errors.apiUrl.message}</p>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor="apiKey">API Key</Label>
              <Input id="apiKey" placeholder="etn_pk_..." {...form.register("apiKey")} />
              {form.formState.errors.apiKey ? (
                <p className="text-xs text-red-600">{form.formState.errors.apiKey.message}</p>
              ) : null}
            </div>
            <p className="text-xs text-zinc-500">
              Klucz wygenerujesz przez CLI: <code>uv run python -m app.cli create-key</code>
            </p>
            <Button className="w-full" type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? "Łączenie..." : "Połącz"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
