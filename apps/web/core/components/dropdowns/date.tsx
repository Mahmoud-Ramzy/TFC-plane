/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
import { createPortal } from "react-dom";
import { usePopper } from "react-popper";
import { CalendarDays } from "lucide-react";
import { Combobox } from "@headlessui/react";
// ui
import type { Matcher } from "@plane/propel/calendar";
import { Calendar } from "@plane/propel/calendar";
import { CloseIcon } from "@plane/propel/icons";
import { ComboDropDown } from "@plane/ui";
import { cn, renderWorkItemDateTime, renderFormattedDate, getDate } from "@plane/utils";
// helpers
// hooks
import { useUserProfile } from "@/hooks/store/user";
import { useDropdown } from "@/hooks/use-dropdown";
// components
import { DropdownButton } from "./buttons";
// constants
import { BUTTON_VARIANTS_WITH_TEXT } from "./constants";
// types
import type { TDropdownProps } from "./types";

type Props = TDropdownProps & {
  clearIconClassName?: string;
  defaultOpen?: boolean;
  /** Enables the optional timezone-free HH:mm time picker under the calendar. */
  enableTime?: boolean;
  optionsClassName?: string;
  icon?: React.ReactNode;
  isClearable?: boolean;
  minDate?: Date;
  maxDate?: Date;
  onChange: (val: Date | null) => void;
  onClose?: () => void;
  value: Date | string | null;
  closeOnSelect?: boolean;
  formatToken?: string;
  renderByDefault?: boolean;
  labelClassName?: string;
};

/** Returns "HH:mm" for wall-clock times, or "" when no time is set (midnight). */
const getTimeInputValue = (date: Date | undefined): string => {
  if (!date || (date.getHours() === 0 && date.getMinutes() === 0)) return "";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
};

/** Returns a copy of the date with the given wall-clock hours/minutes applied. */
const applyTimeToDate = (base: Date, hours: number, minutes: number): Date =>
  new Date(base.getFullYear(), base.getMonth(), base.getDate(), hours, minutes);

/** Returns a copy of the date with the time portion removed. */
const stripTimeFromDate = (base: Date): Date => new Date(base.getFullYear(), base.getMonth(), base.getDate());

export const DateDropdown = observer(function DateDropdown(props: Props) {
  const {
    buttonClassName = "",
    buttonContainerClassName,
    buttonVariant,
    className = "",
    clearIconClassName = "",
    defaultOpen = false,
    enableTime = false,
    optionsClassName = "",
    closeOnSelect = true,
    disabled = false,
    hideIcon = false,
    icon = <CalendarDays className="h-3 w-3 flex-shrink-0" />,
    isClearable = true,
    minDate,
    maxDate,
    onChange,
    onClose,
    placeholder = "Date",
    placement,
    showTooltip = false,
    tabIndex,
    value,
    formatToken,
    renderByDefault = true,
    labelClassName = "",
  } = props;
  // states
  const [isOpen, setIsOpen] = useState(defaultOpen);
  // refs
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  // hooks
  const { data } = useUserProfile();
  const startOfWeek = data?.start_of_the_week;
  // popper-js refs
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null);
  // popper-js init
  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: placement ?? "bottom-start",
    modifiers: [
      {
        name: "preventOverflow",
        options: {
          padding: 12,
        },
      },
    ],
  });

  const isDateSelected = value && value.toString().trim() !== "";

  // Work Item time visibility: when the picker is time-enabled, surface the
  // selected wall-clock time on the closed button as well. Date-only values
  // keep rendering exactly as before.
  const displayLabel = value
    ? enableTime
      ? renderWorkItemDateTime(value)
      : renderFormattedDate(value, formatToken)
    : undefined;

  const onOpen = () => {
    if (referenceElement) referenceElement.focus();
  };

  const { handleClose, handleKeyDown, handleOnClick } = useDropdown({
    dropdownRef,
    isOpen,
    onClose,
    onOpen,
    setIsOpen,
  });

  const dropdownOnChange = (val: Date | null) => {
    onChange(val);
    // With the time picker enabled the popover stays open so the user can
    // adjust the time after picking a date.
    if (closeOnSelect && !enableTime) {
      handleClose();
      referenceElement?.blur();
    }
  };

  // Optional time support (Work Item start/due dates). The time is treated as
  // a timezone-free wall-clock value carried on the existing Date object.
  const [timeInputValue, setTimeInputValue] = useState("");

  useEffect(() => {
    // Re-initialize the native time input from the current value whenever the
    // popover opens or the external value changes while it is open.
    if (!enableTime || !isOpen) return;
    setTimeInputValue(getTimeInputValue(getDate(value)));
  }, [enableTime, isOpen, value]);

  const handleCalendarSelect = (date: Date | undefined) => {
    const pickedDate = date ?? null;
    if (pickedDate && enableTime && timeInputValue) {
      const [hours, minutes] = timeInputValue.split(":").map(Number);
      if (!Number.isNaN(hours) && !Number.isNaN(minutes)) {
        // Preserve an already-entered time when a new date is picked.
        dropdownOnChange(applyTimeToDate(pickedDate, hours, minutes));
        return;
      }
    }
    dropdownOnChange(pickedDate);
  };

  const handleTimeInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextTimeValue = event.target.value;
    setTimeInputValue(nextTimeValue);
    const currentDate = getDate(value);
    if (!nextTimeValue || !currentDate) return;
    const [hours, minutes] = nextTimeValue.split(":").map(Number);
    if (Number.isNaN(hours) || Number.isNaN(minutes)) return;
    onChange(applyTimeToDate(currentDate, hours, minutes));
  };

  const handleRemoveTime = () => {
    setTimeInputValue("");
    const currentDate = getDate(value);
    if (!currentDate) return;
    // Preserve the selected date, removing only the time portion. The
    // popover stays open so the user can pick a new time right away.
    onChange(stripTimeFromDate(currentDate));
  };

  const disabledDays: Matcher[] = [];
  if (minDate) disabledDays.push({ before: minDate });
  if (maxDate) disabledDays.push({ after: maxDate });

  const comboButton = (
    <button
      type="button"
      className={cn(
        "clickable block h-full max-w-full outline-none",
        {
          "cursor-not-allowed text-secondary": disabled,
          "cursor-pointer": !disabled,
        },
        buttonContainerClassName
      )}
      ref={setReferenceElement}
      onClick={handleOnClick}
      disabled={disabled}
    >
      <DropdownButton
        className={buttonClassName}
        isActive={isOpen}
        tooltipHeading={placeholder}
        tooltipContent={displayLabel ?? "None"}
        showTooltip={showTooltip}
        variant={buttonVariant}
        renderToolTipByDefault={renderByDefault}
      >
        {!hideIcon && icon}
        {BUTTON_VARIANTS_WITH_TEXT.includes(buttonVariant) && (
          <span className={cn("flex-grow truncate text-left text-body-xs-medium", labelClassName)}>
            {displayLabel ?? placeholder}
          </span>
        )}
        {isClearable && !disabled && isDateSelected && (
          <CloseIcon
            className={cn("h-2.5 w-2.5 flex-shrink-0", clearIconClassName)}
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onChange(null);
            }}
          />
        )}
      </DropdownButton>
    </button>
  );

  return (
    <ComboDropDown
      as="div"
      ref={dropdownRef}
      tabIndex={tabIndex}
      className={cn("h-full", className)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          if (!isOpen) handleKeyDown(e);
        } else handleKeyDown(e);
      }}
      button={comboButton}
      disabled={disabled}
      renderByDefault={renderByDefault}
    >
      {isOpen &&
        createPortal(
          <Combobox.Options data-prevent-outside-click static>
            <div
              className={cn(
                "z-30 my-1 overflow-hidden rounded-md border-[0.5px] border-strong bg-surface-1 shadow-raised-200",
                optionsClassName
              )}
              ref={setPopperElement}
              style={styles.popper}
              {...attributes.popper}
            >
              <Calendar
                className="rounded-md border border-subtle p-3"
                captionLayout="dropdown"
                selected={getDate(value)}
                defaultMonth={getDate(value)}
                onSelect={handleCalendarSelect}
                showOutsideDays
                initialFocus
                disabled={disabledDays}
                mode="single"
                fixedWeeks
                weekStartsOn={startOfWeek}
              />
              {enableTime && (
                <div className="mt-2 flex items-center justify-between gap-2 border-t border-subtle pt-2">
                  <input
                    type="time"
                    step={60}
                    aria-label="Time"
                    title={isDateSelected ? "Time" : "Select a date first"}
                    value={timeInputValue}
                    disabled={disabled || !isDateSelected}
                    onChange={handleTimeInputChange}
                    className="h-7 rounded-md border-[0.5px] border-strong bg-surface-1 px-2 text-body-xs-regular outline-none placeholder:text-placeholder focus:ring-1 focus:ring-accent-strong disabled:cursor-not-allowed disabled:text-placeholder"
                  />
                  {!disabled && timeInputValue !== "" && (
                    <button
                      type="button"
                      onClick={handleRemoveTime}
                      className="flex flex-shrink-0 items-center gap-1 rounded-sm px-1 py-0.5 text-body-xs-medium text-secondary transition-colors hover:bg-layer-1 hover:text-primary"
                    >
                      <CloseIcon className="h-2.5 w-2.5" />
                      Remove time
                    </button>
                  )}
                </div>
              )}
            </div>
          </Combobox.Options>,
          document.body
        )}
    </ComboDropDown>
  );
});
