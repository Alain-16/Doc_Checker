"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, call, type Schemas } from "./client";

/* All server state goes through TanStack Query: one cache, keyed here. */
export const keys = {
  me: ["me"] as const,
  profile: ["industry-profile"] as const,
  vendors: ["vendors"] as const,
  components: (vendorId?: string) => ["components", vendorId ?? "all"] as const,
  rules: ["rules"] as const,
  rule: (id: string) => ["rules", id] as const,
  draft: (id: string) => ["rule-drafts", id] as const,
  attributes: ["key-attributes"] as const,
  alerts: ["alerts"] as const,
  alertSummary: ["alerts", "summary"] as const,
  users: ["users"] as const,
  conversation: (id: string) => ["conversations", id] as const,
  fileStatus: (id: string) => ["vendor-files", id, "status"] as const,
  vendorFiles: (vendorId?: string) => ["vendor-files", "list", vendorId ?? "all"] as const,
  pages: (fileId: string, from: number, to: number) => ["vendor-files", fileId, "pages", from, to] as const,
  documents: (filters: Record<string, string | undefined>) => ["documents", filters] as const,
  document: (id: string) => ["documents", "detail", id] as const,
  documentTypes: ["document-types"] as const,
  findings: (filters: Record<string, string | undefined>) => ["findings", filters] as const,
  finding: (id: string) => ["findings", "detail", id] as const,
  reviewItems: (filters: Record<string, string | undefined>) => ["review-items", filters] as const,
  vendorStats: ["stats", "vendors"] as const,
  componentStats: (vendorId?: string) => ["stats", "components", vendorId ?? "all"] as const,
  dashboard: ["stats", "dashboard"] as const,
  conversations: ["conversations"] as const,
  alert: (id: string) => ["alerts", "detail", id] as const,
  alertPolicies: ["alert-policies"] as const,
  alertPolicyHistory: (event: string) => ["alert-policies", event] as const,
  owners: (filters: Record<string, string | undefined>) => ["owners", filters] as const,
  presets: ["industry-profile", "presets"] as const,
  ruleKinds: ["rule-kinds"] as const,
};

/** Drops undefined/"All" values so they don't reach the query string. */
function clean<T extends Record<string, unknown>>(filters: T): T {
  return Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== undefined && v !== "" && v !== "All")) as T;
}

/* ---------- Session ---------- */

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => call(api.GET("/auth/me")),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 5 * 60_000,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => call(api.POST("/auth/logout")),
    onSettled: () => qc.clear(),
  });
}

export function useSetDigest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (digest_frequency: Schemas["DigestFrequency"]) =>
      call(api.PUT("/auth/me/preferences", { body: { digest_frequency } })),
    onSuccess: (me) => qc.setQueryData(keys.me, me),
  });
}

export function useIndustryProfile() {
  return useQuery({ queryKey: keys.profile, queryFn: () => call(api.GET("/industry-profile")), staleTime: 10 * 60_000 });
}

/* ---------- Vendors & components ---------- */

export function useVendors() {
  return useQuery({ queryKey: keys.vendors, queryFn: () => call(api.GET("/vendors")) });
}

export function useComponents(vendorId?: string) {
  return useQuery({
    queryKey: keys.components(vendorId),
    queryFn: () => call(api.GET("/components", { params: { query: vendorId ? { vendor_id: vendorId } : {} } })),
  });
}

/* ---------- Upload & processing ---------- */

export async function uploadVendorFile(file: File): Promise<Schemas["UploadAccepted"]> {
  // Multipart by hand: simpler than teaching openapi-fetch a body serializer for one call.
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/vendor-files", { method: "POST", body: form, credentials: "same-origin" });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body?.detail ?? body);
  return body as Schemas["UploadAccepted"];
}

export function useFileStatus(id: string | null, poll: boolean) {
  return useQuery({
    queryKey: keys.fileStatus(id ?? "none"),
    queryFn: () => call(api.GET("/vendor-files/{vendor_file_id}/status", { params: { path: { vendor_file_id: id! } } })),
    enabled: !!id,
    // A file that doesn't exist (404) won't appear by asking again.
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 3,
    refetchInterval: (query) => {
      if (query.state.status === "error") return false;
      const status = query.state.data?.status;
      return poll && (status === "queued" || status === "running" || !status) ? 2000 : false;
    },
  });
}

export function useResumeFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      call(api.POST("/vendor-files/{vendor_file_id}/resume", { params: { path: { vendor_file_id: id } } })),
    onSuccess: (_, id) => qc.invalidateQueries({ queryKey: keys.fileStatus(id) }),
  });
}

/* ---------- Compliance rules ---------- */

export function useRules() {
  return useQuery({ queryKey: keys.rules, queryFn: () => call(api.GET("/compliance-rules")) });
}

export function useRule(id: string) {
  return useQuery({
    queryKey: keys.rule(id),
    queryFn: () => call(api.GET("/compliance-rules/{rule_id}", { params: { path: { rule_id: id } } })),
  });
}

export function useUpdateRule(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["RuleSettings"]) =>
      call(api.PUT("/compliance-rules/{rule_id}", { params: { path: { rule_id: id } }, body })),
    onSuccess: (rule) => {
      qc.setQueryData(keys.rule(id), rule);
      qc.invalidateQueries({ queryKey: keys.rules, exact: true });
    },
  });
}

export function useCreateDraft() {
  return useMutation({ mutationFn: (text: string) => call(api.POST("/rule-drafts", { body: { text } })) });
}

export function useClarifyDraft() {
  return useMutation({
    mutationFn: ({ id, answers }: { id: string; answers: string }) =>
      call(api.POST("/rule-drafts/{draft_id}/clarify", { params: { path: { draft_id: id } }, body: { answers } })),
  });
}

export function useConfirmDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["ConfirmRequest"] }) =>
      call(api.POST("/rule-drafts/{draft_id}/confirm", { params: { path: { draft_id: id } }, body })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.rules });
      qc.invalidateQueries({ queryKey: keys.attributes });
    },
  });
}

/* ---------- Key attributes ---------- */

export function useAttributes() {
  return useQuery({ queryKey: keys.attributes, queryFn: () => call(api.GET("/key-attributes")) });
}

export function useUpdateAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["AttributeChange"] }) =>
      call(api.PUT("/key-attributes/{attribute_id}", { params: { path: { attribute_id: id } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.attributes }),
  });
}

/* ---------- Alerts (the bell) ---------- */

export function useAlertSummary() {
  return useQuery({
    queryKey: keys.alertSummary,
    queryFn: () => call(api.GET("/alerts/summary")),
    refetchInterval: 60_000,
  });
}

export function useAlerts(enabled = true) {
  return useQuery({
    queryKey: keys.alerts,
    queryFn: () => call(api.GET("/alerts", { params: { query: { limit: 50 } } })),
    enabled,
  });
}

export function useAcknowledgeAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      call(api.POST("/alerts/{alert_id}/acknowledge", { params: { path: { alert_id: id } }, body: { note: note || null } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.alerts }),
  });
}

/* ---------- Users (Admin) ---------- */

export function useUsers(enabled: boolean) {
  return useQuery({ queryKey: keys.users, queryFn: () => call(api.GET("/users")), enabled });
}

export function useInviteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["Invitation"]) => call(api.POST("/users", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  });
}

export function useUserAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      a:
        | { kind: "role"; id: string; role: Schemas["UserRole"]; reason: string }
        | { kind: "unlock" | "deactivate"; id: string; reason: string },
    ) => {
      const path = { user_id: a.id };
      if (a.kind === "role") return call(api.PUT("/users/{user_id}/role", { params: { path }, body: { role: a.role, reason: a.reason } }));
      if (a.kind === "unlock") return call(api.POST("/users/{user_id}/unlock", { params: { path }, body: { reason: a.reason } }));
      return call(api.POST("/users/{user_id}/deactivate", { params: { path }, body: { reason: a.reason } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.users }),
  });
}

/* ---------- Copilot ---------- */

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: keys.conversation(id ?? "none"),
    queryFn: () => call(api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: id! } } })),
    enabled: !!id,
    staleTime: Infinity,
  });
}

export async function startConversation(question: string) {
  return call(api.POST("/conversations", { body: { question } }));
}

export async function askFollowUp(conversationId: string, question: string) {
  return call(
    api.POST("/conversations/{conversation_id}/messages", {
      params: { path: { conversation_id: conversationId } },
      body: { question },
    }),
  );
}

/* ---------- Documents (pipeline output) ---------- */

export type DocumentFilters = {
  vendor_id?: string;
  component_id?: string;
  vendor_file_id?: string;
  document_type?: string;
  status?: Schemas["ComplianceStatus"];
  include_superseded?: boolean;
  q?: string;
};

export function useDocuments(filters: DocumentFilters = {}, enabled = true) {
  const query = clean(filters);
  return useQuery({
    queryKey: keys.documents(Object.fromEntries(Object.entries(query).map(([k, v]) => [k, String(v)]))),
    queryFn: () => call(api.GET("/documents", { params: { query: { ...query, limit: 2000 } } })),
    enabled,
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: keys.document(id),
    queryFn: () => call(api.GET("/documents/{document_id}", { params: { path: { document_id: id } } })),
  });
}

export function usePages(fileId: string | undefined, from: number, to: number) {
  return useQuery({
    queryKey: keys.pages(fileId ?? "none", from, to),
    queryFn: () =>
      call(api.GET("/vendor-files/{vendor_file_id}/pages", { params: { path: { vendor_file_id: fileId! }, query: { from, to } } })),
    enabled: !!fileId,
    staleTime: Infinity,
  });
}

export function useVendorFiles(vendorId?: string) {
  return useQuery({
    queryKey: keys.vendorFiles(vendorId),
    queryFn: () => call(api.GET("/vendor-files", { params: { query: vendorId ? { vendor_id: vendorId } : {} } })),
  });
}

export function useDocumentTypes() {
  return useQuery({ queryKey: keys.documentTypes, queryFn: () => call(api.GET("/document-types")), staleTime: 5 * 60_000 });
}

/* ---------- Findings (read-only: the rules engine opens and resolves them) ---------- */

export type FindingFilters = {
  status?: "open" | "resolved" | "all";
  severity?: Schemas["FindingSeverity"];
  vendor_id?: string;
  component_id?: string;
  document_id?: string;
  rule_code?: string;
};

export function useFindings(filters: FindingFilters = {}, enabled = true) {
  const query = clean(filters);
  return useQuery({
    queryKey: keys.findings(query as Record<string, string>),
    queryFn: () => call(api.GET("/findings", { params: { query: { ...query, limit: 2000 } } })),
    enabled,
  });
}

export function useFinding(id: string | null) {
  return useQuery({
    queryKey: keys.finding(id ?? "none"),
    queryFn: () => call(api.GET("/findings/{finding_id}", { params: { path: { finding_id: id! } } })),
    enabled: !!id,
  });
}

/* ---------- Review queue ---------- */

export function useReviewItems(
  filters: { status?: "open" | "resolved" | "all"; document_id?: string; vendor_id?: string; vendor_file_id?: string } = {},
) {
  const query = clean(filters);
  return useQuery({
    queryKey: keys.reviewItems(query as Record<string, string>),
    queryFn: () => call(api.GET("/review-items", { params: { query: { ...query, limit: 1000 } } })),
  });
}

export function useReviewItem(id: string | null) {
  return useQuery({
    queryKey: ["review-items", "detail", id ?? "none"],
    queryFn: () => call(api.GET("/review-items/{item_id}", { params: { path: { item_id: id! } } })),
    enabled: !!id,
  });
}

export function useResolveReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["Decision"] }) =>
      call(api.POST("/review-items/{item_id}/resolve", { params: { path: { item_id: id } }, body })),
    onSuccess: () => {
      // A decision re-judges documents: statuses, findings and counts all move.
      for (const k of ["review-items", "documents", "document-types", "findings", "stats", "alerts"]) qc.invalidateQueries({ queryKey: [k] });
    },
  });
}

/* ---------- Statistics ---------- */

export function useVendorStats() {
  return useQuery({ queryKey: keys.vendorStats, queryFn: () => call(api.GET("/vendors/stats")) });
}

export function useComponentStats(vendorId?: string) {
  return useQuery({
    queryKey: keys.componentStats(vendorId),
    queryFn: () => call(api.GET("/components/stats", { params: { query: vendorId ? { vendor_id: vendorId } : {} } })),
  });
}

export function useDashboard() {
  return useQuery({ queryKey: keys.dashboard, queryFn: () => call(api.GET("/dashboard")), refetchInterval: 60_000 });
}

/* ---------- Copilot history ---------- */

export function useConversations() {
  return useQuery({ queryKey: keys.conversations, queryFn: () => call(api.GET("/conversations")) });
}

/* ---------- Alerts: detail and policies ---------- */

export function useAlert(id: string | null) {
  return useQuery({
    queryKey: keys.alert(id ?? "none"),
    queryFn: () => call(api.GET("/alerts/{alert_id}", { params: { path: { alert_id: id! } } })),
    enabled: !!id,
  });
}

export function useAlertPolicies() {
  return useQuery({ queryKey: keys.alertPolicies, queryFn: () => call(api.GET("/alert-policies")) });
}

export function useAlertPolicyHistory(event: Schemas["AlertEvent"] | null) {
  return useQuery({
    queryKey: keys.alertPolicyHistory(event ?? "none"),
    queryFn: () => call(api.GET("/alert-policies/{event}", { params: { path: { event: event! } } })),
    enabled: !!event,
  });
}

export function useUpdateAlertPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ event, body }: { event: Schemas["AlertEvent"]; body: Schemas["PolicySettings"] }) =>
      call(api.PUT("/alert-policies/{event}", { params: { path: { event } }, body })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alert-policies"] });
      qc.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}

/* ---------- Owners (Admin) ---------- */

export function useOwners(filters: { vendor_id?: string; component_id?: string }, enabled: boolean) {
  const query = clean(filters);
  return useQuery({
    queryKey: keys.owners(query),
    queryFn: () => call(api.GET("/owners", { params: { query } })),
    enabled,
  });
}

export function useAssignOwner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["OwnerCreate"]) => call(api.POST("/owners", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["owners"] }),
  });
}

export function useRemoveOwner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      call(api.POST("/owners/{assignment_id}/remove", { params: { path: { assignment_id: id } }, body: { reason } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["owners"] }),
  });
}

/* ---------- Industry profile (Admin) ---------- */

export function usePresets(enabled: boolean) {
  return useQuery({ queryKey: keys.presets, queryFn: () => call(api.GET("/industry-profile/presets")), enabled, staleTime: Infinity });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ProfileChange"]) => call(api.PUT("/industry-profile", { body })),
    onSuccess: (profile) => qc.setQueryData(keys.profile, profile),
  });
}

/* ---------- Key attributes & rules: direct creation ---------- */

export function useCreateAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["AttributeCreate"]) => call(api.POST("/key-attributes", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.attributes }),
  });
}

export function useRuleKinds() {
  return useQuery({ queryKey: keys.ruleKinds, queryFn: () => call(api.GET("/compliance-rules/kinds")), staleTime: Infinity });
}

export function useCreateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["RuleCreate"]) => call(api.POST("/compliance-rules", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.rules }),
  });
}
