// Image rights: what may go public, what the credit line says, and who to ask.

export const RIGHTS = ['own', 'public', 'needs-permission', 'confidential'];

/** The source file an entry is made from: what a permission or a catalogue row refers to. */
export const sourceKey = (item) => item?.source?.file ?? item?.source?.video ?? item?.source?.pdf ?? '';

/** Permission counts only for the exact file the holder agreed to, not for whatever later replaces it. */
const permissionCovers = (item) => item.permission?.status === 'granted' && item.permission.source === sourceKey(item);

/** May this image appear in the public build? Own and openly licensed work, or recorded permission. */
export const isCleared = (item) =>
  item.rights === 'own' || item.rights === 'public' || (item.rights === 'needs-permission' && permissionCovers(item));

export const holderText = (item) => [].concat(item.holder ?? []).join(' + ') || 'the rights holder';

/** What has to happen before an image can go public: labels, a level and who to ask. */
export function rightsStatus(item, quality) {
  const granted = permissionCovers(item);
  let label;
  let short;
  let level;
  switch (item.rights) {
    case 'own':
      label = 'Own work';
      short = 'Own';
      level = 'clear';
      break;
    case 'public':
      label = `Public: ${item.license || 'license not recorded'}`;
      short = item.license || 'Public';
      level = item.license ? 'clear' : 'check';
      break;
    case 'needs-permission':
      if (granted) {
        label = `Permission granted: ${holderText(item)}`;
        short = 'Permission granted';
      } else if (item.permission?.status === 'refused') {
        label = `Refused by ${holderText(item)}: take it off the page`;
        short = 'Refused';
      } else {
        const asked = item.permission?.status === 'requested' ? ' (asked, waiting)' : '';
        label = `Ask ${holderText(item)}${asked}`;
        short = `Ask ${holderText(item)}${asked}`;
      }
      level = granted ? 'clear' : 'blocked';
      break;
    case 'confidential':
      label = 'Confidential: never publish';
      short = 'Confidential';
      level = 'blocked';
      break;
    default:
      label = 'Rights unknown';
      short = 'Rights?';
      level = 'blocked';
  }
  if (quality === 'low') {
    label += ' · low resolution';
    if (level === 'clear') level = 'check';
  }
  return { label, short, level };
}

/** The line shown with every image: who made it and, where it matters, on what terms. */
export function creditLine(item) {
  const parts = [item.credit];
  if (item.rights === 'public' && item.license) parts.push(item.license);
  if (item.rights === 'needs-permission' && permissionCovers(item)) parts.push('used with permission');
  return parts.filter(Boolean).join(' · ');
}
