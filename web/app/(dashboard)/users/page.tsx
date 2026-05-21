"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createUser,
  createUserApiKey,
  deactivateUser,
  listUserApiKeys,
  listUsers,
  revokeApiKey,
  updateUser,
} from "@/lib/api/client";
import type { ApiKeyOut, UserCreateInput, UserOut, UserRole } from "@/lib/api/types";

type EditableUser = {
  email: string;
  role: UserRole;
  active: boolean;
  lms_username: string;
};

function asRole(value: string): UserRole {
  if (value === "admin" || value === "editor" || value === "viewer") {
    return value;
  }
  return "viewer";
}

export default function UsersPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, EditableUser>>({});
  const [apiKeys, setApiKeys] = useState<Record<string, ApiKeyOut[]>>({});
  const [rawKeyByUser, setRawKeyByUser] = useState<Record<string, string>>({});
  const [newUser, setNewUser] = useState<UserCreateInput>({
    username: "",
    email: "",
    role: "viewer",
  });
  const [keyNameByUser, setKeyNameByUser] = useState<Record<string, string>>({});

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: ({ signal }) => listUsers(signal),
  });

  const createUserMutation = useMutation({
    mutationFn: (body: UserCreateInput) => createUser(body),
    onSuccess: () => {
      toast.success("Użytkownik utworzony");
      setNewUser({ username: "", email: "", role: "viewer" });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const updateUserMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: EditableUser }) =>
      updateUser(id, {
        email: body.email,
        role: body.role,
        active: body.active,
        lms_username: body.lms_username || null,
      }),
    onSuccess: () => {
      toast.success("Użytkownik zaktualizowany");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deactivateUserMutation = useMutation({
    mutationFn: (id: string) => deactivateUser(id),
    onSuccess: () => {
      toast.success("Użytkownik zdezaktywowany");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const createApiKeyMutation = useMutation({
    mutationFn: ({ userId, name }: { userId: string; name: string }) =>
      createUserApiKey(userId, { name }),
    onSuccess: (created, variables) => {
      setRawKeyByUser((prev) => ({ ...prev, [variables.userId]: created.raw_key }));
      toast.success("Nowy API key został wygenerowany");
      void loadKeys(variables.userId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const revokeApiKeyMutation = useMutation({
    mutationFn: ({ keyId }: { keyId: string; userId: string }) => revokeApiKey(keyId),
    onSuccess: (_, variables) => {
      toast.success("Klucz API został cofnięty");
      void loadKeys(variables.userId);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  async function loadKeys(userId: string): Promise<void> {
    const keys = await listUserApiKeys(userId);
    setApiKeys((prev) => ({ ...prev, [userId]: keys }));
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-zinc-900">Użytkownicy i API keys</h1>

      <Card>
        <CardHeader>
          <CardTitle>Dodaj użytkownika</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-4">
          <Input
            placeholder="username"
            value={newUser.username}
            onChange={(event) => setNewUser((prev) => ({ ...prev, username: event.target.value }))}
          />
          <Input
            placeholder="email"
            type="email"
            value={newUser.email}
            onChange={(event) => setNewUser((prev) => ({ ...prev, email: event.target.value }))}
          />
          <select
            className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
            value={newUser.role}
            onChange={(event) =>
              setNewUser((prev) => ({ ...prev, role: asRole(event.target.value) }))
            }
          >
            <option value="viewer">viewer</option>
            <option value="editor">editor</option>
            <option value="admin">admin</option>
          </select>
          <Button
            onClick={() => createUserMutation.mutate(newUser)}
            disabled={!newUser.username || !newUser.email}
          >
            Utwórz
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Lista użytkowników</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {usersQuery.isLoading ? <p className="text-sm text-zinc-500">Ładowanie...</p> : null}
          {(usersQuery.data ?? []).map((user: UserOut) => {
            const draft = drafts[user.id] ?? {
              email: user.email,
              role: asRole(user.role),
              active: user.active,
              lms_username: user.lms_username ?? "",
            };
            const userKeys = apiKeys[user.id] ?? [];
            const keyName = keyNameByUser[user.id] ?? "main";
            const rawKey = rawKeyByUser[user.id];

            return (
              <div key={user.id} className="space-y-2 rounded-md border border-zinc-200 p-3">
                <div className="grid gap-2 lg:grid-cols-6">
                  <Input disabled value={user.username} />
                  <Input
                    type="email"
                    value={draft.email}
                    onChange={(event) => {
                      setDrafts((prev) => ({
                        ...prev,
                        [user.id]: { ...draft, email: event.target.value },
                      }));
                    }}
                  />
                  <select
                    className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
                    value={draft.role}
                    onChange={(event) => {
                      setDrafts((prev) => ({
                        ...prev,
                        [user.id]: { ...draft, role: asRole(event.target.value) },
                      }));
                    }}
                  >
                    <option value="viewer">viewer</option>
                    <option value="editor">editor</option>
                    <option value="admin">admin</option>
                  </select>
                  <Input
                    placeholder="lms username"
                    value={draft.lms_username}
                    onChange={(event) => {
                      setDrafts((prev) => ({
                        ...prev,
                        [user.id]: { ...draft, lms_username: event.target.value },
                      }));
                    }}
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.active}
                      onChange={(event) => {
                        setDrafts((prev) => ({
                          ...prev,
                          [user.id]: { ...draft, active: event.target.checked },
                        }));
                      }}
                    />
                    Aktywny
                  </label>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => updateUserMutation.mutate({ id: user.id, body: draft })}
                    >
                      Zapisz
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => deactivateUserMutation.mutate(user.id)}
                    >
                      Dezaktywuj
                    </Button>
                  </div>
                </div>

                <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                  <Input
                    placeholder="Nazwa klucza"
                    value={keyName}
                    onChange={(event) => {
                      setKeyNameByUser((prev) => ({ ...prev, [user.id]: event.target.value }));
                    }}
                  />
                  <Button size="sm" variant="outline" onClick={() => void loadKeys(user.id)}>
                    Odśwież klucze
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => createApiKeyMutation.mutate({ userId: user.id, name: keyName })}
                  >
                    Generuj klucz
                  </Button>
                </div>

                {rawKey ? (
                  <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    Raw key (pokazywany tylko raz): <code>{rawKey}</code>
                  </div>
                ) : null}

                {userKeys.length > 0 ? (
                  <div className="space-y-1">
                    {userKeys.map((key) => (
                      <div
                        key={key.id}
                        className="flex items-center justify-between rounded border border-zinc-200 px-3 py-1.5 text-xs"
                      >
                        <span>
                          {key.name} · created: {new Date(key.created_at).toLocaleString()}
                          {key.revoked_at ? " · revoked" : ""}
                        </span>
                        {!key.revoked_at ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              revokeApiKeyMutation.mutate({ keyId: key.id, userId: user.id })
                            }
                          >
                            Revoke
                          </Button>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
