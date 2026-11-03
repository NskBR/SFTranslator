import {forwardRef,useImperativeHandle,type HTMLAttributes} from "react";
import {motion,useAnimation} from "motion/react";
import type {LucideIcon} from "lucide-react";
import {animatedIcon} from "./animatedIcon";
/** Small companion gestures for Lucide symbols absent from the upstream collection. */
export function animatedLucide(Icon:LucideIcon,name:string,gesture:"tilt"|"pulse"|"bounce"="pulse"){
 const Svg=motion.create(Icon);
 const Source=forwardRef<{startAnimation:()=>void;stopAnimation:()=>void},HTMLAttributes<HTMLSpanElement>&{size?:number}>(({size=24},ref)=>{
  const controls=useAnimation();
  useImperativeHandle(ref,()=>({startAnimation:()=>{void controls.start("animate");},stopAnimation:()=>{void controls.start("normal");}}),[controls]);
  return <span><Svg size={size} initial={false} animate={controls} variants={{normal:{rotate:0,scale:1,y:0},animate:gesture==="tilt"?{rotate:[0,-12,8,0]}:gesture==="bounce"?{y:[0,-2,0]}:{scale:[1,1.12,1]}}} transition={{duration:.42,ease:"easeInOut"}}/></span>;
 });
 return animatedIcon(Source,name);
}
