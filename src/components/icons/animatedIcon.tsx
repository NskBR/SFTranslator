import {useEffect,useRef,type ComponentType,type RefAttributes,type HTMLAttributes} from "react";
import type {LucideProps} from "lucide-react";
interface AnimationHandle {startAnimation:()=>void;stopAnimation:()=>void}
type SourceIcon=ComponentType<HTMLAttributes<HTMLSpanElement>&{size?:number}&RefAttributes<AnimationHandle>>;
/** Keep icon motion local to the control: no timers, global hover listener or app-transition dependency. */
export function animatedIcon(Icon:SourceIcon,name:string){
 function Animated({size=24,className,style,color,strokeWidth=2,"aria-label":label}:LucideProps){
  const root=useRef<HTMLSpanElement>(null);const controls=useRef<AnimationHandle>(null);
  useEffect(()=>{
   const element=root.current;if(!element)return;
   const target=element.closest<HTMLElement>("button,a,[role='button'],[role='tab']")??element;
   const reduced=typeof matchMedia==="function"?matchMedia("(prefers-reduced-motion: reduce)"):null;
   let hovered=false,focused=false,running=false;
   const update=()=>{
    const next=(hovered||focused)&&document.documentElement.dataset.animatedIcons==="on"&&!reduced?.matches&&!target.matches(":disabled,[aria-disabled='true']");
    if(next===running)return;running=next;element.dataset.animating=String(next);
    if(next)controls.current?.startAnimation();else controls.current?.stopAnimation();
   };
   const enter=()=>{hovered=true;update();};const leave=()=>{hovered=false;update();};
   const focus=()=>{focused=target.matches(":focus-visible");update();};const blur=()=>{focused=false;update();};
   target.addEventListener("mouseenter",enter);target.addEventListener("mouseleave",leave);
   target.addEventListener("focusin",focus);target.addEventListener("focusout",blur);
   reduced?.addEventListener("change",update);
   return()=>{target.removeEventListener("mouseenter",enter);target.removeEventListener("mouseleave",leave);target.removeEventListener("focusin",focus);target.removeEventListener("focusout",blur);reduced?.removeEventListener("change",update);};
  },[]);
  return <span ref={root} className={`sf-animated-icon ${className??""}`} data-icon={name} aria-label={label} aria-hidden={label?undefined:true}
   style={{...style,color:color??style?.color,"--sf-icon-stroke":strokeWidth} as React.CSSProperties}>
   <Icon ref={controls} size={typeof size==="number"?size:24}/>
  </span>;
 }
 Animated.displayName=`Animated(${name})`;return Animated;
}
