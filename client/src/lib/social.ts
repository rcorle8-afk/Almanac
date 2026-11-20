// The social layer (M5): friends, the bell, groups, public profiles and reports. Mirrors
// server/social_api.py and server/social.py by hand.

import type { HeldBadge } from "./achievements";
import type { AvatarConfig } from "./types";

/** How one account appears to others. */
export interface Card {
  public_id: string;
  name: string;
  handle: string | null;
  avatar: AvatarConfig;
  level: number;
  prestige: number;
}

export type Relation = "you" | "friend" | "requested" | "incoming" | "blocked" | "none";

/** A group's icon: one of the server's drawings on one of its colours (social.GROUP_GLYPHS and
 *  GROUP_COLORS), or the address of a picture its owner uploaded, which is drawn instead. */
export interface GroupIconData {
  glyph: string;
  color: string;
  image: string | null;
}

export interface GroupSummary {
  public_id: string;
  name: string;
  icon: GroupIconData;
  member_count: number;
  prestige: number; // its members' prestige, added up
  role: "owner" | "member" | null;
}

/** What an invite link shows before joining, signed in or not. */
export interface GroupPreview extends GroupSummary {
  bio: string;
  max_members: number;
  owner: { name: string; avatar: AvatarConfig };
}

export interface GroupInvite extends GroupSummary {
  invited_by: Card | null;
  at: string;
}

export interface Overview {
  me: Card & { friend_code: string };
  friends: (Card & { since: string })[]; // ranked by prestige: the friends leaderboard
  incoming: (Card & { at: string })[];
  outgoing: (Card & { at: string })[];
  tablemates: (Card & { last_played: string; relation: Relation })[];
  groups: GroupSummary[];
  group_invites: GroupInvite[];
  coins: number;
  group_cost: number; // coins to start a group
  groups_left: number; // how many more you may own
}

export interface PublicProfile extends Card {
  bio: string;
  bio_hidden: boolean; // only ever true on your own profile
  games: number;
  wins: number;
  best_quotes: number;
  badges: HeldBadge[];
  relation: Relation;
  groups: { public_id: string; name: string }[];
}

export interface GroupDetail {
  public_id: string;
  name: string;
  name_hidden: boolean; // only ever true for the owner
  bio: string;
  bio_hidden: boolean; // only ever true for the owner
  icon: GroupIconData;
  image_hidden: boolean; // only ever true for the owner
  invite_code: string | null; // the code in the invite link; members only
  owner: Card;
  role: "owner" | "member" | null;
  invited: boolean;
  by_link: boolean; // invited by following the link, with nothing stored to decline
  members: (Card & { role: "owner" | "member"; joined_at: string; you: boolean })[]; // by prestige
  member_count: number;
  prestige: number; // its members' prestige, added up
  max_members: number;
  invitable: Card[]; // the owner's friends who aren't in it yet
  pending: Card[]; // invited, not yet answered
}

/** One player on the global board. `place` is shared by equal prestige. */
export interface LeaderboardPlayer extends Card {
  place: number;
  you: boolean;
}

/** One group on the global board, ranked by its members' combined prestige. */
export interface LeaderboardGroup {
  place: number;
  public_id: string;
  name: string;
  icon: GroupIconData;
  member_count: number;
  prestige: number;
  role: "owner" | "member" | null; // yours, if you're in it
}

/** The global leaderboard: the top of each board, and where you and your groups stand. */
export interface Leaderboard {
  players: LeaderboardPlayer[];
  player_count: number; // everyone ranked, not only those listed
  you: { place: number | null; prestige: number }; // no place until you have prestige
  groups: LeaderboardGroup[];
  group_count: number;
  your_groups: { place: number; public_id: string; name: string }[]; // best first
}

export type NotificationKind = "friend_request" | "friend_accepted" | "group_invite" | "group_joined" | "room_invite";

export interface Notification {
  id: number;
  kind: NotificationKind;
  at: string;
  read: boolean;
  actor: Card | null;
  group: { public_id: string; name: string } | null;
  room_code: string | null;
  open: boolean; // a request or invite that can still be answered
}

export type ReportKind = "bio" | "group_name" | "group_bio" | "group_image";

export interface ReviewItem {
  id: number;
  kind: ReportKind;
  text: string;
  image: string | null; // a reported picture, as it is now
  at: string;
  owner: Card | null;
  group: { public_id: string; name: string } | null;
  reporters: Card[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    let message = "Something went wrong.";
    try {
      message = (await response.json()).detail ?? message;
    } catch {
      // not JSON; keep the generic message
    }
    throw new Error(message);
  }
  return response.json();
}

function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return call<T>(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const id = encodeURIComponent;

export const fetchOverview = () => call<Overview>("/api/social");
export const searchHandles = async (q: string) =>
  (await call<{ results: (Card & { relation: Relation })[] }>(`/api/social/search?q=${id(q)}`)).results;
export const saveHandle = async (handle: string) =>
  (await send<{ handle: string | null }>("PUT", "/api/profile/handle", { handle })).handle;
export const newFriendCode = async () =>
  (await send<{ friend_code: string }>("POST", "/api/profile/friend-code")).friend_code;
export const fetchPublicProfile = (publicId: string) => call<PublicProfile>(`/api/u/${id(publicId)}`);

type Answer = Promise<{ relation: Relation }>;
export const addFriend = (publicId: string): Answer => send("POST", "/api/friends", { public_id: publicId });
export const addFriendByCode = (code: string): Answer => send("POST", "/api/friends", { friend_code: code });
export const acceptFriend = (publicId: string): Answer => send("POST", `/api/friends/${id(publicId)}/accept`);
export const declineFriend = (publicId: string): Answer => send("POST", `/api/friends/${id(publicId)}/decline`);
export const removeFriend = (publicId: string): Answer => send("DELETE", `/api/friends/${id(publicId)}`);
export const blockPlayer = (publicId: string): Answer => send("POST", `/api/blocks/${id(publicId)}`);
export const unblockPlayer = (publicId: string): Answer => send("DELETE", `/api/blocks/${id(publicId)}`);

export const fetchLeaderboard = () => call<Leaderboard>("/api/leaderboard");

export const fetchNotifications = () => call<{ unread: number; items: Notification[] }>("/api/notifications");
export const markNotificationsRead = () => send<{ unread: number }>("POST", "/api/notifications/read");

/** Starts a group, for Overview.group_cost coins. The bio and icon can be chosen now or later. */
export const createGroup = (group: { name: string; bio?: string; glyph?: string; color?: string }) =>
  send<GroupSummary>("POST", "/api/groups", group);
export const fetchMyGroups = async () => (await call<{ groups: GroupSummary[] }>("/api/groups/mine")).groups;
const linkQuery = (invite?: string | null) => (invite ? `?invite=${id(invite)}` : "");
/** `invite` is the code from an invite link, when that's how the player got here. */
export const fetchGroup = (publicId: string, invite?: string | null) =>
  call<GroupDetail>(`/api/groups/${id(publicId)}${linkQuery(invite)}`);
export const fetchGroupPreview = (publicId: string, invite: string) =>
  call<GroupPreview>(`/api/groups/${id(publicId)}/preview${linkQuery(invite)}`);
/** The owner's edits; anything left out stays as it is. */
export const changeGroup = (publicId: string, change: { name?: string; bio?: string; glyph?: string; color?: string }) =>
  send<GroupDetail>("PATCH", `/api/groups/${id(publicId)}`, change);
export const renameGroup = (publicId: string, name: string) => changeGroup(publicId, { name });
export const uploadGroupImage = async (publicId: string, picture: Blob) =>
  (
    await call<{ icon: GroupIconData }>(`/api/groups/${id(publicId)}/image`, {
      method: "PUT",
      headers: { "Content-Type": picture.type || "application/octet-stream" },
      body: picture,
    })
  ).icon;
export const removeGroupImage = async (publicId: string) =>
  (await send<{ icon: GroupIconData }>("DELETE", `/api/groups/${id(publicId)}/image`)).icon;
/** A new code for the invite link; every copy of the old link stops working. */
export const resetInviteLink = async (publicId: string) =>
  (await send<{ invite_code: string }>("POST", `/api/groups/${id(publicId)}/invite-link`)).invite_code;
/** The link a member shares. Whoever opens it can join, after signing in. */
export const inviteLink = (publicId: string, code: string) => `${location.origin}/g/${id(publicId)}${linkQuery(code)}`;
export const disbandGroup = (publicId: string) => send("DELETE", `/api/groups/${id(publicId)}`);
export const inviteToGroup = (publicId: string, member: string) =>
  send<{ result: string }>("POST", `/api/groups/${id(publicId)}/invites`, { public_id: member });
export const joinGroup = (publicId: string, invite?: string | null) =>
  send<GroupSummary>("POST", `/api/groups/${id(publicId)}/join`, invite ? { invite } : undefined);
export const declineGroup = (publicId: string) => send("POST", `/api/groups/${id(publicId)}/decline`);
export const leaveGroup = (publicId: string) => send("POST", `/api/groups/${id(publicId)}/leave`);
export const removeMember = (publicId: string, member: string) =>
  send("DELETE", `/api/groups/${id(publicId)}/members/${id(member)}`);

export const report = (kind: ReportKind, publicId: string) =>
  send("POST", "/api/reports", { kind, public_id: publicId });
export const fetchReviewQueue = async () => (await call<{ reports: ReviewItem[] }>("/api/admin/reports")).reports;
export const resolveReport = (reportId: number, action: "restore" | "clear") =>
  send("POST", `/api/admin/reports/${reportId}`, { action });

/** An accuracy flag (M6 anti-cheat) with the player's recent quotes, from /api/admin/flags. */
export interface AccuracyFlag {
  id: number;
  status: "open" | "cleared" | "confirmed";
  player: { name: string; public_id: string; handle: string | null };
  quotes: number;
  bullseyes: number;
  rate: number;
  baseline: number;
  p_value: number;
  beats: number | null; // more accurate than this many of `regulars` other regular players
  regulars: number | null;
  created_at: string;
  reviewed_at: string | null;
  recent: {
    question: string | null;
    unit: string | null;
    bid: string;
    ask: string;
    answer: string;
    bullseye: boolean;
    off_percent: number;
    spread: number | null; // ask / bid
    seconds: number | null;
    played: string;
  }[];
}

export const fetchFlags = () =>
  call<{ flags: AccuracyFlag[]; min_quotes: number; bullseye_ratio: string }>("/api/admin/flags");
export const decideFlag = (flagId: number, action: "clear" | "confirm") =>
  send("POST", `/api/admin/flags/${flagId}`, { action });

/** Fired on window when the bell accepts or declines something, so a page showing the same
 *  requests or invites can reload instead of going stale. */
export const SOCIAL_CHANGED = "almanac:social-changed";

/** Reloads with `load` whenever the bell changes something. Returns the cleanup. */
export function onSocialChange(load: () => void): () => void {
  window.addEventListener(SOCIAL_CHANGED, load);
  return () => window.removeEventListener(SOCIAL_CHANGED, load);
}

/** "ABCD2345" as people read it aloud: "ABCD-2345". */
export const formatCode = (code: string) => `${code.slice(0, 4)}-${code.slice(4)}`;

/** What a relation's friend button says, and whether it does anything. */
export function friendLabel(relation: Relation | null | undefined): { label: string; active: boolean } {
  switch (relation) {
    case "friend":
      return { label: "Friends", active: false };
    case "requested":
      return { label: "Requested", active: false };
    case "incoming":
      return { label: "Accept", active: true };
    case "blocked":
      return { label: "Blocked", active: false };
    case "you":
      return { label: "You", active: false };
    default:
      return { label: "Add friend", active: true };
  }
}
