"use client";

import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type User } from "@/lib/api";

const ROLES = ["admin", "instructor", "learner"] as const;

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", password: "", role: "instructor", org_unit: "" });
  const [error, setError] = useState<string | null>(null);
  const load = () => api.get<User[]>("/users").then(setUsers);

  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/users", { ...form, org_unit: form.org_unit || null });
      setOpen(false);
      setForm({ email: "", name: "", password: "", role: "instructor", org_unit: "" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <Shell title="Users" actions={<Button size="sm" variant="accent" onClick={() => setOpen((v) => !v)}><Plus /> Add user</Button>}>
      <div className="container space-y-6 py-6">
        {open && (
          <Card className="animate-fade-in">
            <CardHeader><CardTitle>New account</CardTitle></CardHeader>
            <CardContent>
              <form onSubmit={create} className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5"><Label>Name</Label><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
                <div className="space-y-1.5"><Label>Email</Label><Input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
                <div className="space-y-1.5"><Label>Temporary password</Label><Input required minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
                <div className="space-y-1.5">
                  <Label>Role</Label>
                  <select className="flex h-9 w-full rounded-md border border-input bg-surface px-3 text-sm" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
                <div className="space-y-1.5 md:col-span-2"><Label>Org unit (optional)</Label><Input value={form.org_unit} onChange={(e) => setForm({ ...form, org_unit: e.target.value })} /></div>
                {error && <p className="text-sm text-destructive md:col-span-2">{error}</p>}
                <div className="flex gap-2 md:col-span-2"><Button type="submit" variant="accent">Create</Button><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button></div>
              </form>
            </CardContent>
          </Card>
        )}
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground"><tr className="border-b"><th className="py-2 pr-3 font-medium">Name</th><th className="py-2 pr-3 font-medium">Email</th><th className="py-2 pr-3 font-medium">Role</th><th className="py-2 pr-3 font-medium">Org unit</th><th className="py-2 font-medium">Status</th><th /></tr></thead>
          <tbody className="divide-y">
            {users.map((u) => (
              <tr key={u.id}>
                <td className="py-2 pr-3">{u.name}</td>
                <td className="py-2 pr-3 font-mono text-xs">{u.email}</td>
                <td className="py-2 pr-3"><Badge tone={u.role === "admin" ? "accent" : "neutral"}>{u.role}</Badge></td>
                <td className="py-2 pr-3 text-muted-foreground">{u.org_unit ?? "—"}</td>
                <td className="py-2">{u.is_active ? <Badge tone="success">active</Badge> : <Badge tone="destructive">inactive</Badge>}</td>
                <td className="py-2 text-right">{u.is_active && <Button size="sm" variant="ghost" onClick={() => confirm(`Deactivate ${u.email}?`) && api.del(`/users/${u.id}`).then(load)}>Deactivate</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}
