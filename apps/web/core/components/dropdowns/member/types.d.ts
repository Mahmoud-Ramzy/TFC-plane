import type { TDropdownProps } from "../types";

export type MemberDropdownProps = TDropdownProps & {
  button?: React.ReactNode;
  dropdownArrow?: boolean;
  dropdownArrowClassName?: string;
  placeholder?: string;
  tooltipContent?: string;
  onClose?: () => void;
  showUserDetails?: boolean;
  /** When true, invitation-only project Guests are listed as assignable candidates. Defaults to false. */
  includeGuests?: boolean;
} & (
    | {
        multiple: false;
        onChange: (val: string | null) => void;
        value: string | null;
      }
    | {
        multiple: true;
        onChange: (val: string[]) => void;
        value: string[];
      }
  );
