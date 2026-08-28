# Feature matrix

Status legend: **implemented**, **partial**, **planned**, **upstream**.

| Capability | Desktop PWA | Mobile PWA | Android 0.4.0-alpha01 | Apple alpha03 | Notes |
|---|---|---|---|---|---|
| Floodman staff login | implemented | implemented | implemented | implemented | Local or Gauzy-linked identity paths |
| Full Gauzy ERP | upstream via launcher | not primary | not exposed | not exposed | External HTTPS route protected by staff access policy |
| Customer search/files | implemented | implemented | implemented | partial | Apple detail parity remains |
| Notes and tags | implemented | implemented | implemented | partial | |
| Properties | implemented | implemented | implemented | partial | Customer-scoped selection |
| Documents | implemented | implemented | implemented | partial | Signed files link to customer/job |
| CSV/ZIP imports | implemented | implemented | not primary | not primary | Staff administrative workflow |
| Estimate search/create | implemented | implemented | implemented | partial | |
| Editable grouped headers | implemented | implemented | implemented | partial | |
| Catalog/custom lines | implemented | implemented | implemented | partial | Custom lines persist |
| Project-plan templates | implemented | implemented | implemented | partial | Category-driven |
| Estimate PDF/send/sign | implemented | implemented | implemented | partial | Real RoomFlow layout only |
| Deposit/payment/convert | implemented | implemented | implemented | partial | Square/manual methods |
| Invoice create/edit/send | implemented | implemented | implemented | partial | |
| Card/cash/check/ACH | implemented | implemented | implemented | partial | Raw PAN/CVV never stored |
| Calendar/appointments | implemented | implemented | implemented | partial | Jobs/inspections/follow-ups/etc. |
| Employee assignment | implemented | implemented | implemented | partial | Multiple + lead employee |
| Conflict detection | implemented | implemented | implemented | partial | Controlled override |
| Tasks/announcements | implemented | implemented | implemented | partial | |
| Notifications | implemented | implemented | implemented | partial | Provider push requires credentials |
| Time clock | implemented | implemented | implemented | implemented/basic | |
| RoomFlow full engine | implemented | implemented | implemented/bundled | implemented/bundled | Pinned external source |
| RoomFlow Supabase import | implemented | implemented | implemented | bridge source present | Server-side import |
| RoomFlow workspaces | implemented | implemented | implemented | partial | |
| Dark/light/system theme | implemented | implemented | implemented | implemented | |
| Offline assigned-job cache | partial | service-worker cache | partial | planned | Needs production hardening |
| Camera/document queue | browser-dependent | browser-dependent | partial | planned | |
| Production push | planned/configurable | N/A | planned | planned | FCM/APNs credentials required |
| TestFlight distribution | N/A | N/A | N/A | planned | Apple signing required |
